"""Менеджер намерений: RAM + SQLite, жизненный цикл, восстановление.

RAM — быстрый доступ к активным намерениям. SQLite — сохранение между
перезапусками. Поддерживается пересмотр, изменение приоритета, отмена,
устаревание и консолидация похожих намерений.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from main_logger import logger

from .intention import Intention


class IntentionManager:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._db_path = db_path
        self._active: Dict[str, Intention] = {}  # id -> intention (RAM)
        self._conn: Optional[sqlite3.Connection] = None
        if db_path:
            self._init_db()

    # ------------------------------------------------------------- storage

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intentions (
                    id TEXT PRIMARY KEY,
                    character_id TEXT,
                    type TEXT,
                    description TEXT,
                    priority INTEGER,
                    status TEXT,
                    created_at REAL,
                    conditions TEXT,
                    expiry REAL,
                    context TEXT
                )
                """
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning("[IntentionManager] db init failed: %s", exc)
            self._conn = None

    def _load_from_db(self) -> None:
        if self._conn is None:
            return
        try:
            rows = self._conn.execute(
                "SELECT * FROM intentions WHERE status IN ('created','waiting','ready')"
            ).fetchall()
            for row in rows:
                data = {
                    "id": row[0],
                    "character_id": row[1],
                    "type": row[2],
                    "description": row[3],
                    "priority": row[4],
                    "status": row[5],
                    "created_at": row[6],
                    "conditions": self._loads(row[7]),
                    "expiry": row[8],
                    "context": self._loads(row[9]),
                }
                intention = Intention.from_dict(data)
                if intention.is_active():
                    self._active[intention.id] = intention
            logger.info("[IntentionManager] restored %d intention(s)", len(self._active))
        except Exception as exc:
            logger.warning("[IntentionManager] load failed: %s", exc)

    @staticmethod
    def _loads(value: Any) -> Any:
        if not value:
            return {}
        try:
            import json

            return json.loads(value)
        except Exception:
            return {}

    @staticmethod
    def _dumps(value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=False)

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        self._load_from_db()

    def create(
        self,
        *,
        character_id: str,
        type: str,
        description: str,
        priority: int = 1,
        conditions: Optional[Dict[str, Any]] = None,
        expiry: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Intention:
        intention = Intention(
            character_id=character_id,
            type=type,
            description=description,
            priority=priority,
            conditions=conditions or {},
            expiry=expiry,
            context=context or {},
        )
        with self._lock:
            self._active[intention.id] = intention
            self._upsert_db(intention)
        return intention

    def get(self, intention_id: str) -> Optional[Intention]:
        with self._lock:
            return self._active.get(intention_id)

    def list_active(self, character_id: Optional[str] = None) -> List[Intention]:
        with self._lock:
            result = [i for i in self._active.values() if i.is_active()]
            if character_id:
                result = [i for i in result if i.character_id == character_id]
            return sorted(result, key=lambda i: -i.priority)

    def set_status(self, intention_id: str, status: str) -> bool:
        with self._lock:
            intention = self._active.get(intention_id)
            if intention is None:
                return False
            if status in ("completed", "cancelled", "expired"):
                self._active.pop(intention_id, None)
            else:
                intention.status = status
            self._upsert_db(intention)
            return True

    def set_priority(self, intention_id: str, priority: int) -> bool:
        with self._lock:
            intention = self._active.get(intention_id)
            if intention is None:
                return False
            intention.priority = int(priority)
            self._upsert_db(intention)
            return True

    def cancel(self, intention_id: str) -> bool:
        return self.set_status(intention_id, "cancelled")

    # ---------------------------------------------------------- maintenance

    def prune_expired(self) -> int:
        """Отменить устаревшие намерения."""
        now = time.time()
        expired = []
        with self._lock:
            for iid, intention in list(self._active.items()):
                if intention.expiry is not None and now > intention.expiry:
                    expired.append(iid)
            for iid in expired:
                self.set_status(iid, "expired")
        return len(expired)

    def consolidate(self) -> int:
        """Объединить похожие намерения одного персонажа (по типу)."""
        removed = 0
        with self._lock:
            by_character: Dict[str, Dict[str, List[Intention]]] = {}
            for intention in self._active.values():
                by_character.setdefault(intention.character_id, {}).setdefault(
                    intention.type, []
                ).append(intention)
            for char_map in by_character.values():
                for group in char_map.values():
                    if len(group) < 2:
                        continue
                    # Оставляем один с максимальным приоритетом, остальные отменяем.
                    group.sort(key=lambda i: -i.priority)
                    keep = group[0]
                    for dup in group[1:]:
                        self._active.pop(dup.id, None)
                        self.set_status(dup.id, "cancelled")
                        removed += 1
                    keep.priority = max(i.priority for i in group)
                    self._upsert_db(keep)
        return removed

    # -------------------------------------------------------- stage 6 additions

    def evaluate_conditions(self, intention: Intention, context: str = "") -> bool:
        """Проверить условия выполнения намерения (если указаны)."""
        cond = intention.conditions or {}
        if not cond:
            return True
        now = time.time()
        after = cond.get("after_ts")
        if after is not None and now < float(after):
            return False
        before = cond.get("before_ts")
        if before is not None and now > float(before):
            return False
        keywords = cond.get("need_topic_in")
        if keywords:
            ctx = str(context or "").lower()
            tokens = ctx.split()
            for k in keywords:
                key = str(k).strip().lower()
                if not key:
                    continue
                if key in ctx:
                    return True
                # Свободное совпадение по корню (мин. 3 символа).
                if len(key) >= 3 and any(
                    (len(t) >= len(key) and t[: len(key)] == key)
                    or (len(t) >= 3 and t[:3] == key[:3])
                    for t in tokens
                ):
                    return True
            return False
        return True

    def mark_ready(
        self, character_id: Optional[str] = None, context: str = ""
    ) -> int:
        """Перевести намерения в 'ready', если их условия выполнены."""
        changed = 0
        with self._lock:
            for intention in list(self._active.values()):
                if intention.status not in ("created", "waiting"):
                    continue
                if character_id and intention.character_id != character_id:
                    continue
                if self.evaluate_conditions(intention, context):
                    intention.status = "ready"
                    self._upsert_db(intention)
                    changed += 1
        return changed

    def promote_by_relevance(self, keywords, amount: int = 1, cap: int = 5) -> int:
        """Повысить приоритет активных намерений, связанных с ключевыми словами."""
        if not keywords:
            return 0
        keys = [str(k).strip().lower() for k in keywords if str(k).strip()]
        if not keys:
            return 0
        promoted = 0
        with self._lock:
            for intention in list(self._active.values()):
                if not intention.is_active():
                    continue
                hay = " ".join(
                    [
                        intention.type,
                        intention.description,
                        str(intention.conditions or ""),
                    ]
                ).lower()
                if any(k in hay for k in keys):
                    if int(intention.priority) < int(cap):
                        intention.priority = int(intention.priority) + int(amount)
                        self._upsert_db(intention)
                        promoted += 1
        return promoted

    # -------------------------------------------------------------- internal

    def _upsert_db(self, intention: Intention) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO intentions
                    (id, character_id, type, description, priority, status,
                     created_at, conditions, expiry, context)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    intention.id,
                    intention.character_id,
                    intention.type,
                    intention.description,
                    intention.priority,
                    intention.status,
                    intention.created_at,
                    self._dumps(intention.conditions),
                    intention.expiry,
                    self._dumps(intention.context),
                ),
            )
            self._conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

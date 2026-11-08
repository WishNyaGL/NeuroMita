"""Обработчик событий: дедупликация, фильтрация, объединение."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


class EventProcessor:
    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}
        self._hook: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_hook(self, hook: Callable[[Dict[str, Any]], None]) -> None:
        """Колбэк, получающий обработанное событие (например, движок)."""
        self._hook = hook

    def push(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        *,
        source: Optional[str] = None,
    ) -> None:
        event = {"type": event_type, "data": data or {}, "ts": time.time()}
        if source is not None:
            event["source"] = source
        if not self._should_keep(event):
            return
        if self._hook is not None:
            try:
                self._hook(event)
            except Exception:
                pass

    # ------------------------------------------------------------- filters

    def _should_keep(self, event: Dict[str, Any]) -> bool:
        # Дедупликация: одинаковые события в коротком окне пропускаем.
        key = self._dedup_key(event)
        now = event["ts"]
        last = self._seen.get(key)
        if last is not None and now - last < 2.0:
            return False
        self._seen[key] = now
        # Очистка устаревших ключей.
        if len(self._seen) > 500:
            cutoff = now - 60.0
            self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}
        # Фильтр: технические/шумовые события с минимальной значимостью.
        if key.startswith("noise."):
            return False
        return True

    @staticmethod
    def _dedup_key(event: Dict[str, Any]) -> str:
        data = event.get("data") or {}
        # Для сообщений/ответов ключ включает персонажа, чтобы не терять разные.
        char = str(data.get("character_id") or data.get("character_name") or "").strip()
        text = str(data.get("text") or data.get("response") or "").strip()[:40]
        return f"{event['type']}|{char}|{text}"

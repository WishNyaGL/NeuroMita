"""Ядро Initiative Engine.

Координатор системы: управляет жизненным циклом, связывает scheduler, систему
наблюдения и точки входа для событий. На этапе 2 подключено наблюдение за
диалогом (EventBus) и Windows (MCP). Принятие решений добавляется позже.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from main_logger import logger

from .config import InitiativeConfig
from .scheduler import InitiativeScheduler
from .observation import ObservationManager
from .perception import PerceptionEngine
from .motivation import MotivationSystem
from .decision import DecisionContext, DecisionEngine
from .intentions import IntentionManager
from .actions import InitiativeActionManager, PermissionPolicy
from .feedback import FeedbackSystem


class InitiativeEngine:
    def __init__(
        self,
        config: Optional[InitiativeConfig] = None,
        *,
        loop: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        mcp_service: Optional[Any] = None,
        character_registry: Optional[Any] = None,
        intentions_db_path: Optional[str] = None,
        tool_manager: Optional[Any] = None,
        chat_api: Optional[Any] = None,
        activity_service: Optional[Any] = None,
    ) -> None:
        self.config = config or InitiativeConfig()
        self._loop = loop
        self._event_bus = event_bus
        self._mcp_service = mcp_service
        self._character_registry = character_registry
        self._intentions_db_path = intentions_db_path
        self._tool_manager = tool_manager
        self._chat_api = chat_api
        self._activity_service = activity_service
        self._scheduler: Optional[InitiativeScheduler] = None
        self._observation: Optional[ObservationManager] = None
        self._perception: Optional[PerceptionEngine] = None
        self._motivation: Optional[MotivationSystem] = None
        self._decision: Optional[DecisionEngine] = None
        self._intentions: Optional[IntentionManager] = None
        self._actions: Optional[InitiativeActionManager] = None
        self._feedback: Optional[FeedbackSystem] = None
        self._lock = threading.RLock()
        self._running = False
        self._pending_events: List[Dict[str, Any]] = []
        self._last_window_context = ""
        self._last_decision: Optional[Dict[str, Any]] = None
        self._last_perception: Optional[Dict[str, Any]] = None
        self._stats = {
            "ticks": 0,
            "events_total": 0,
            "events_filtered": 0,
            "decisions": {},
            "actions_executed": 0,
            "intentions_active": 0,
            "intentions_completed": 0,
            "last_decision": None,
            "last_perception": None,
            "started_at": None,
        }

    # ------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            if not self.config.enabled:
                return
            self._running = True
            self._scheduler = InitiativeScheduler(
                interval_sec=self.config.scheduler_interval_sec,
                on_tick=self._on_tick,
                loop=self._loop,
            )
            self._scheduler.start()
            self._init_observation()
            self._perception = PerceptionEngine(self._character_registry)
            self._motivation = MotivationSystem()
            self._decision = DecisionEngine(
                max_initiatives_per_minute=self.config.max_actions_per_minute
            )
            self._intentions = IntentionManager(self._intentions_db_path)
            self._intentions.start()
            self._actions = InitiativeActionManager(
                tool_manager=self._tool_manager,
                chat_api=self._chat_api,
            )
            self._feedback = FeedbackSystem()
            logger.info(
                "[InitiativeEngine] started (autonomy=%s, scheduler=%ss, "
                "observe_dialogue=%s, observe_windows=%s)",
                self.config.autonomy_level,
                self.config.scheduler_interval_sec,
                self.config.observe_dialogue,
                self.config.observe_windows,
            )
            if self._observation is not None:
                logger.info("[InitiativeEngine] monitoring attached (EventBus)")
            if self._intentions is not None:
                logger.info(
                    "[InitiativeEngine] intentions restored (%d active)",
                    len(self._intentions.list_active()),
                )

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._scheduler is not None:
                self._scheduler.stop()
                self._scheduler = None
            if self._observation is not None:
                self._observation.detach()
                self._observation = None
            if self._intentions is not None:
                try:
                    self._intentions.prune_expired()
                    self._intentions.consolidate()
                    self._intentions.close()
                except Exception:
                    pass
                self._intentions = None
            logger.info("[InitiativeEngine] stopped")

    def apply_config(self, config: Optional[InitiativeConfig] = None) -> None:
        """Применить новую конфигурацию на лету (без перезапуска приложения).

        Пересоздаёт scheduler и decision с новыми параметрами, если движок
        запущен. Остальные параметры читаются из config каждый тик, поэтому
        подхватываются автоматически.
        """
        if config is not None:
            self.config = config
        with self._lock:
            if not self._running:
                return
            # Пересоздаём scheduler с новым интервалом.
            if self._scheduler is not None:
                self._scheduler.stop()
            self._scheduler = InitiativeScheduler(
                interval_sec=self.config.scheduler_interval_sec,
                on_tick=self._on_tick,
                loop=self._loop,
            )
            self._scheduler.start()
            # Обновляем решение с новым лимитом.
            if self._decision is not None:
                self._decision = DecisionEngine(
                    max_initiatives_per_minute=self.config.max_actions_per_minute
                )
            logger.info(
                "[InitiativeEngine] config applied (scheduler=%ss, max_actions=%d)",
                self.config.scheduler_interval_sec,
                self.config.max_actions_per_minute,
            )

    # --------------------------------------------------------------- events

    def receive_event(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Внешний вход события (если наблюдение отключено)."""
        if not self._running:
            return
        with self._lock:
            self._pending_events.append({"type": name, "data": data or {}})
        if self._scheduler is not None:
            self._scheduler.trigger_async()

    # ------------------------------------------------------------ observation

    def _init_observation(self) -> None:
        if self._observation is not None:
            return
        self._observation = ObservationManager(
            event_bus=self._event_bus,
            mcp_service=self._mcp_service,
        )
        self._observation.set_hook(self._on_observation)
        self._observation.attach()

    def _on_observation(self, event: Dict[str, Any]) -> None:
        """Обработанное событие из системы наблюдения."""
        with self._lock:
            self._pending_events.append(event)
        if self._scheduler is not None:
            self._scheduler.trigger_async()

    # ------------------------------------------------------------ internals

    def _on_tick(self) -> None:
        """Периодическая оценка: наблюдение + восприятие (заглушка решения)."""
        if not self._running:
            return
        self._stats["ticks"] += 1
        if self.config.observe_windows and self._observation is not None:
            try:
                self._observation.poll_windows()
                self._last_window_context = self._last_window_context
            except Exception:
                pass
        with self._lock:
            pending = self._pending_events
            self._pending_events = []
        self._stats["events_total"] += len(pending)
        if self.config.filter_events and pending:
            filtered = [e for e in pending if not self._is_noise_event(e)]
            self._stats["events_filtered"] += len(pending) - len(filtered)
            pending = filtered
        # Если персонаж занят генерацией — не принимать инициативных решений.
        char_id = self._active_character_id()
        if self.config.respect_busy_character and self._is_character_busy(char_id):
            if self.config.enable_logging:
                logger.info("[InitiativeEngine] tick skipped: character busy (%s)", char_id)
            return
        # Формируем понимание ситуации и принимаем решение.
        if self._perception is not None and self._decision is not None:
            try:
                perception = self._perception.perceive(
                    character_id=char_id,
                    events=pending,
                    window_context=self._last_window_context or None,
                )
                self._last_perception = perception
                motives = self._motivation.evaluate(perception) if self._motivation else []
                ctx = DecisionContext(
                    character_id=str(perception.get("character_id") or ""),
                    perception=perception,
                    motives=motives,
                    can_initiate_dialogue=self.config.allow_initiate_dialogue,
                    actions_available=self.config.autonomy_level in ("subtle", "full"),
                )
                self._last_decision = self._decision.decide(ctx)
                action = str(self._last_decision.get("action") or "")
                self._stats["decisions"].setdefault(action, 0)
                self._stats["decisions"][action] += 1
                self._stats["last_decision"] = {
                    "action": action,
                    "reason": self._last_decision.get("reason"),
                    "char": perception.get("character_id"),
                }
                if self.config.enable_logging:
                    logger.info(
                        "[InitiativeEngine] tick#%d events:%d decision=%s reason=%s char=%s",
                        self._stats["ticks"],
                        len(pending),
                        action,
                        self._last_decision.get("reason"),
                        perception.get("character_id"),
                    )
                if action != "silence":
                    self._execute_decision(
                        self._last_decision,
                        character_id=str(perception.get("character_id") or ""),
                    )
                # Сохраняем мотивы как намерения (для долгосрочного поведения).
                self._materialize_intentions(
                    character_id=str(perception.get("character_id") or ""),
                    motives=motives,
                )
            except Exception:
                pass

    def stats(self) -> Dict[str, Any]:
        """Снимок статистики движка для мониторинга."""
        with self._lock:
            intentions = self._intentions.list_active() if self._intentions else []
            completed = self._intentions.list_active() if self._intentions else []
            stats = dict(self._stats)
            stats["intentions_active"] = len(intentions)
            stats["last_perception"] = self._last_perception
            stats["running"] = self._running
            stats["config"] = {
                "enabled": self.config.enabled,
                "autonomy_level": self.config.autonomy_level,
                "scheduler_interval_sec": self.config.scheduler_interval_sec,
                "max_actions_per_minute": self.config.max_actions_per_minute,
                "filter_events": self.config.filter_events,
                "respect_busy_character": self.config.respect_busy_character,
            }
            return stats

    def set_logging(self, enabled: bool) -> None:
        self.config = self.config.__class__(
            **{**self.config.__dict__, "enable_logging": bool(enabled)}
        )

    def _is_character_busy(self, character_id: Optional[str]) -> bool:
        if self._activity_service is None:
            return False
        try:
            return self._activity_service.active_generation_count(character_id) > 0
        except Exception:
            return False

    @staticmethod
    def _is_noise_event(event: Dict[str, Any]) -> bool:
        """Отфильтровать технические/повторяющиеся события низкой значимости."""
        etype = str(event.get("type") or "")
        # События, которые не должны триггерить инициативу в одиночку.
        if etype in (
            "on_compression_started",
            "on_compression_finished",
            "on_tool_done",
            "on_failed_attempt_for_response",
        ):
            return True
        # Пустые события.
        data = event.get("data") or {}
        if not data:
            return True
        return False

    def _active_character_id(self) -> Optional[str]:
        if self._character_registry is None:
            return None
        try:
            return self._character_registry.current_id()
        except Exception:
            return None

    def _execute_decision(self, decision: Dict[str, Any], *, character_id: str) -> None:
        """Исполнить принятое решение (если это действие), затем обработать feedback."""
        if self._actions is None or not character_id:
            return
        action = str(decision.get("action") or "")
        result = None
        try:
            if action == "initiate_dialogue":
                reason = str(decision.get("reason") or "")
                self._actions.initiate_dialogue(character_id, reason)
                # Разговор начат — считаем успехом (подтверждение придёт из событий).
                result = "[InitiativeAction] dialogue initiated"
            elif action == "act":
                meta = decision.get("meta") or {}
                motive = meta.get("motive") or {}
                tool = str(motive.get("type") or "").replace("comment_on_window", "show_notification")
                result = self._actions.execute_tool(character_id, tool, {})
        except Exception as exc:
            logger.warning("[InitiativeEngine] execute decision failed: %s", exc)
            result = f"[ошибка] {exc}"

        if self._feedback is not None and result is not None and action != "silence":
            try:
                feedback = self._feedback.process(
                    intention=decision.get("meta") or {},
                    action_result=result,
                )
                if feedback.get("action") == "retry":
                    # Провал: помечаем намерение для пересмотра (уменьшаем приоритет).
                    self._degrade_active_intention(character_id, decision.get("meta") or {})
                elif feedback.get("action") == "complete":
                    self._complete_active_intention(character_id, decision.get("meta") or {})
            except Exception:
                pass

    def _degrade_active_intention(self, character_id: str, meta: Dict[str, Any]) -> None:
        if self._intentions is None:
            return
        motive = meta.get("motive") or {}
        mtype = str(motive.get("type") or "")
        for intention in self._intentions.list_active(character_id):
            if intention.type == mtype:
                self._intentions.set_priority(intention.id, max(0, intention.priority - 1))
                break

    def _complete_active_intention(self, character_id: str, meta: Dict[str, Any]) -> None:
        if self._intentions is None:
            return
        motive = meta.get("motive") or {}
        mtype = str(motive.get("type") or "")
        for intention in self._intentions.list_active(character_id):
            if intention.type == mtype:
                self._intentions.set_status(intention.id, "completed")
                break

    def _materialize_intentions(
        self, *, character_id: str, motives: List[Dict[str, Any]]
    ) -> None:
        """Превратить значимые мотивы в намерения (если ещё нет таких)."""
        if not character_id or self._intentions is None:
            return
        try:
            existing = {
                i.type for i in self._intentions.list_active(character_id)
            }
            for motive in motives:
                mtype = str(motive.get("type") or "")
                if not mtype or mtype in existing:
                    continue
                if int(motive.get("priority", 0)) < 2:
                    continue  # только значимые мотивы становятся намерениями
                self._intentions.create(
                    character_id=character_id,
                    type=mtype,
                    description=str(motive.get("description") or ""),
                    priority=int(motive.get("priority", 1)),
                    context={"source": motive.get("source", "")},
                )
                existing.add(mtype)
        except Exception:
            pass

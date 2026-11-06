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
    ) -> None:
        self.config = config or InitiativeConfig()
        self._loop = loop
        self._event_bus = event_bus
        self._mcp_service = mcp_service
        self._character_registry = character_registry
        self._intentions_db_path = intentions_db_path
        self._scheduler: Optional[InitiativeScheduler] = None
        self._observation: Optional[ObservationManager] = None
        self._perception: Optional[PerceptionEngine] = None
        self._motivation: Optional[MotivationSystem] = None
        self._decision: Optional[DecisionEngine] = None
        self._intentions: Optional[IntentionManager] = None
        self._lock = threading.RLock()
        self._running = False
        self._pending_events: List[Dict[str, Any]] = []
        self._last_window_context = ""
        self._last_decision: Optional[Dict[str, Any]] = None

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
            logger.info("[InitiativeEngine] started (autonomy=%s)", self.config.autonomy_level)

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
        if self.config.observe_windows and self._observation is not None:
            try:
                self._observation.poll_windows()
                self._last_window_context = self._last_window_context
            except Exception:
                pass
        with self._lock:
            pending = self._pending_events
            self._pending_events = []
        # Формируем понимание ситуации и принимаем решение.
        if self._perception is not None and self._decision is not None:
            try:
                perception = self._perception.perceive(
                    character_id=self._active_character_id(),
                    events=pending,
                    window_context=self._last_window_context or None,
                )
                motives = self._motivation.evaluate(perception) if self._motivation else []
                ctx = DecisionContext(
                    character_id=str(perception.get("character_id") or ""),
                    perception=perception,
                    motives=motives,
                    can_initiate_dialogue=self.config.allow_initiate_dialogue,
                    actions_available=self.config.autonomy_level in ("subtle", "full"),
                )
                self._last_decision = self._decision.decide(ctx)
                if self._last_decision.get("action") != "silence":
                    logger.info(
                        "[InitiativeEngine] decision=%s reason=%s char=%s",
                        self._last_decision.get("action"),
                        self._last_decision.get("reason"),
                        perception.get("character_id"),
                    )
                # Сохраняем мотивы как намерения (для долгосрочного поведения).
                self._materialize_intentions(
                    character_id=str(perception.get("character_id") or ""),
                    motives=motives,
                )
            except Exception:
                pass

    def _active_character_id(self) -> Optional[str]:
        if self._character_registry is None:
            return None
        try:
            return self._character_registry.current_id()
        except Exception:
            return None

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

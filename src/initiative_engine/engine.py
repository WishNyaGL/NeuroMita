"""Ядро Initiative Engine.

Координатор системы: управляет жизненным циклом, связывает scheduler и точки
входа для событий. На Этапе 1 не содержит сложного автономного поведения —
это каркас, который корректно встраивается в NeuroMita, не нарушая её работу.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from main_logger import logger

from .config import InitiativeConfig
from .scheduler import InitiativeScheduler


class InitiativeEngine:
    def __init__(
        self,
        config: Optional[InitiativeConfig] = None,
        *,
        loop: Optional[Any] = None,
    ) -> None:
        self.config = config or InitiativeConfig()
        self._loop = loop
        self._scheduler: Optional[InitiativeScheduler] = None
        self._lock = threading.RLock()
        self._running = False
        self._pending_events: List[Dict[str, Any]] = []

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
            logger.info("[InitiativeEngine] started (autonomy=%s)", self.config.autonomy_level)

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._scheduler is not None:
                self._scheduler.stop()
                self._scheduler = None
            logger.info("[InitiativeEngine] stopped")

    # ----------------------------------------------------------------- events

    def receive_event(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Принять событие окружения/диалога.

        Используется интеграционным слоем NeuroMita. На этапе 1 события просто
        накапливаются; фильтрация/обработка добавляются на этапе 2.
        """
        if not self._running:
            return
        with self._lock:
            self._pending_events.append({"type": name, "data": data or {}})
        # Важные события могут запросить немедленную оценку.
        if self._scheduler is not None:
            self._scheduler.trigger_async()

    # ------------------------------------------------------------ internals

    def _on_tick(self) -> None:
        """Периодическая оценка. На этапе 1 — заглушка.

        Здесь позже будет вызываться PerceptionEngine → DecisionEngine и
        выполняться решение (промолчать / заговорить / действовать).
        """
        if not self._running:
            return
        with self._lock:
            pending = self._pending_events
            self._pending_events = []
        if pending:
            logger.debug("[InitiativeEngine] tick, %d pending event(s)", len(pending))

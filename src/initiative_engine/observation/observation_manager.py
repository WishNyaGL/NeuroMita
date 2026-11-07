"""Observation Manager: собирает события из источников и передаёт в EventProcessor.

Источники:
- события диалога/модели NeuroMita через EventBus;
- события/состояние Windows через MCP (опрос по расписанию).
"""
from __future__ import annotations

from typing import Any, Optional

from main_logger import logger

from .event_processor import EventProcessor
from .source import EventSource, normalize_source


class ObservationManager:
    def __init__(
        self,
        *,
        event_bus: Any,
        mcp_service: Any = None,
        processor: Optional[EventProcessor] = None,
    ) -> None:
        self._event_bus = event_bus
        self._mcp_service = mcp_service
        self._processor = processor or EventProcessor()
        self._subscriptions = []

    # ----------------------------------------------------------------- setup

    def set_hook(self, hook) -> None:
        self._processor.set_hook(hook)

    def attach(self) -> None:
        if self._event_bus is None or self._subscriptions:
            return
        try:
            from core.events import Events

            subs = [
                (Events.Chat.SEND_MESSAGE, self._on_dialogue_event),
                (Events.Model.ON_SUCCESSFUL_RESPONSE, self._on_dialogue_event),
                (Events.Model.ON_TOOL_DONE, self._on_tool_event),
            ]
            for name, cb in subs:
                self._event_bus.subscribe(name, cb, weak=False)
                self._subscriptions.append((name, cb))
            logger.debug("[InitiativeObservation] attached to EventBus")
        except Exception as exc:
            logger.warning("[InitiativeObservation] attach failed: %s", exc)

    def detach(self) -> None:
        for name, cb in self._subscriptions:
            try:
                self._event_bus.unsubscribe(name, cb)
            except Exception:
                pass
        self._subscriptions = []

    # ---------------------------------------------------------- event hooks

    def _on_dialogue_event(self, event: Any) -> None:
        name = getattr(event, "name", None) or ""
        data = getattr(event, "data", None) or {}
        source = normalize_source(name, data)
        self._processor.push(name, data, source=source.value)

    def _on_tool_event(self, event: Any) -> None:
        name = getattr(event, "name", None) or ""
        data = getattr(event, "data", None) or {}
        # Инструменты — значимые события, но без дедупликации по тексту.
        tool = str(data.get("tool_name") or "").strip()
        self._processor.push(
            f"tool.{tool}",
            {"character_id": data.get("character_id")},
            source=EventSource.TOOL.value,
        )

    # --------------------------------------------------------- windows (MCP)

    def poll_windows(self) -> None:
        """Опрос Windows-состояния через MCP (по расписанию).

        На этапе 2 — лёгкие наблюдения (активное окно / процессы), без
        скриншота на каждом цикле.
        """
        if self._mcp_service is None:
            return
        try:
            active = self._mcp_service.call_tool("get_active_window", {}, timeout=5.0)
            if "active window" in str(active):
                self._processor.push("windows.active_window", {"summary": str(active)[:120]})
        except Exception:
            pass

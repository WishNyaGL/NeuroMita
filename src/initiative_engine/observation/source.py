"""Нормализация источника события для Initiative Engine.

Единое внутреннее представление происхождения события. Категории:
- player      — явное обращение пользователя (sender="Player");
- system      — системная реплика/ответ персонажа (sender="System");
- initiative  — инициатива самого движка (резервируется);
- tool        — результат исполнения инструмента;
- external    — внешние события (таймеры, напоминания, игровые задачи);
- unknown     — источник достоверно не определён (НЕ считается player).

Определение идёт только по достоверным метаданным (sender/event_type/task_uid),
никогда по тексту сообщения.
"""
from __future__ import annotations

import enum
from typing import Any, Dict, Optional


class EventSource(str, enum.Enum):
    PLAYER = "player"
    SYSTEM = "system"
    INITIATIVE = "initiative"
    TOOL = "tool"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


# event_type из внешних/системных источников, которые НЕ являются
# пользовательским обращением и НЕ должны классифицироваться как player.
_EXTERNAL_EVENT_TYPES = frozenset(
    {
        "timer",
        "reminder",
        "idle_timeout",
        "camera",
        "camera_snapshot_result",
        "periodic",
        "game_master_observe",
        "game_master_command",
    }
)


def normalize_source(event_type: str, data: Optional[Dict[str, Any]] = None) -> EventSource:
    """Вернуть категорию источника по метаданным события.

    ``event_type`` — имя события (например, ``send_message`` или ``tool.<tool>``),
    ``data`` — payload события. Явного/достоверного признака нет → ``unknown``.
    """
    etype = str(event_type or "").strip()
    data = data if isinstance(data, dict) else {}

    # Инструменты.
    if etype.startswith("tool."):
        return EventSource.TOOL

    # Наблюдения за окном — внешние события окружения.
    if etype == "windows.active_window":
        return EventSource.EXTERNAL

    # События диалога.
    sender = str(data.get("sender") or data.get("from") or "").strip().lower()
    if sender == "player":
        return EventSource.PLAYER
    if sender == "system":
        # sender="System" НЕ является достаточным признаком инициативы —
        # это системная реплика/ответ персонажа.
        return EventSource.SYSTEM

    # Внешние типы событий.
    ev_type = str(data.get("event_type") or "").strip().lower()
    if ev_type in _EXTERNAL_EVENT_TYPES:
        return EventSource.EXTERNAL

    # Игровые/Unity-задачи и повторы.
    if data.get("task_uid") or data.get("unity_retry_message_id"):
        return EventSource.EXTERNAL

    # Всё прочее без достоверного признака — неизвестно.
    return EventSource.UNKNOWN

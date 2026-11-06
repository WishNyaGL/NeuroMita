"""Конфигурация Initiative Engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class InitiativeConfig:
    """Настройки движка инициативы.

    Значения по умолчанию консервативны: движок выключен, чтобы не менять
    существующее поведение NeuroMita до явного включения.
    """

    enabled: bool = False

    # Частота принятия решений (сек). hybrid: события + периодическая оценка.
    scheduler_interval_sec: float = 30.0

    # Уровень автономности: "off" | "subtle" | "full".
    autonomy_level: str = "off"

    # Максимум инициативных действий в минуту (защита от зацикливания).
    max_actions_per_minute: int = 2

    # Разрешено ли движку начинать разговор через ChatAPI.initiate().
    allow_initiate_dialogue: bool = True

    # Источники наблюдений.
    observe_dialogue: bool = True
    observe_windows: bool = True

    # Использовать ли screenshot для восприятия (vision).
    use_vision: bool = False

    # Только персонажи, для которых включена инициатива (пусто = все).
    enabled_characters: List[str] = field(default_factory=list)

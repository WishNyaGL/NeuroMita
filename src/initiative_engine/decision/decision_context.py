"""Контекст решения: восприятие + мотивы + доступные действия."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DecisionContext:
    character_id: str = ""
    perception: Dict[str, Any] = field(default_factory=dict)
    motives: List[Dict[str, Any]] = field(default_factory=list)
    # Ограничения среды/политики.
    can_initiate_dialogue: bool = True
    actions_available: bool = True
    recent_initiatives: List[float] = field(default_factory=list)

"""Модель намерения персонажа."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Intention:
    """Намерение — то, чего персонаж хочет достичь в будущем.

    Жизненный цикл: created -> waiting -> ready -> executing -> completed /
    cancelled / expired.
    """

    character_id: str
    type: str
    description: str
    priority: int = 1
    status: str = "created"  # created|waiting|ready|executing|completed|cancelled|expired
    created_at: float = field(default_factory=time.time)
    conditions: Dict[str, Any] = field(default_factory=dict)
    expiry: Optional[float] = None
    context: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def is_active(self) -> bool:
        return self.status in ("created", "waiting", "ready", "executing")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "character_id": self.character_id,
            "type": self.type,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
            "conditions": self.conditions,
            "expiry": self.expiry,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Intention":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            character_id=str(data.get("character_id") or ""),
            type=str(data.get("type") or ""),
            description=str(data.get("description") or ""),
            priority=int(data.get("priority") or 1),
            status=str(data.get("status") or "created"),
            created_at=float(data.get("created_at") or time.time()),
            conditions=data.get("conditions") or {},
            expiry=data.get("expiry"),
            context=data.get("context") or {},
        )

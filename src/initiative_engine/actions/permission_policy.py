"""Политика разрешений на инициативные действия.

Full-автономность не означает отсутствие ограничений: персонаж может сам
выбирать цели, но потенциально опасные операции контролируются здесь.
"""
from __future__ import annotations

# Действия, которые по умолчанию запрещены для автономного выполнения.
_BLOCKED_ACTIONS = {
    "close_process",
    "close_neuromita",
    "lock_screen",
    "fake_bsod",
}


class PermissionPolicy:
    def __init__(self, *, blocked_actions=None) -> None:
        self._blocked = set(blocked_actions or _BLOCKED_ACTIONS)

    def can_execute(self, action: str, *, character_id: str = "") -> bool:
        action = str(action or "").strip()
        if not action:
            return False
        if action in self._blocked:
            return False
        return True

    def block(self, action: str) -> None:
        self._blocked.add(str(action or "").strip())

    def allow(self, action: str) -> None:
        self._blocked.discard(str(action or "").strip())

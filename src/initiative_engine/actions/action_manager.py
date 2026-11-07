"""Координатор выполнения инициативных действий.

Выполняет разрешённые действия через существующие интерфейсы NeuroMita:
- начало разговора — ChatAPI.initiate();
- инструменты — ToolManager / MCP.

Учитывает character_generation_lock, чтобы автономные решения не конкурировали
с активным диалогом пользователя.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from main_logger import logger

from .permission_policy import PermissionPolicy


class InitiativeActionManager:
    def __init__(
        self,
        *,
        permission_policy: Optional[PermissionPolicy] = None,
        tool_manager: Any = None,
        chat_api: Any = None,
    ) -> None:
        self._policy = permission_policy or PermissionPolicy()
        self._tool_manager = tool_manager
        self._chat_api = chat_api

    # ------------------------------------------------------------- dialogue

    def initiate_dialogue(self, character_id: str, instruction: str) -> bool:
        """Начать самостоятельный разговор от имени системы."""
        if not self._policy.can_execute("dialogue.initiate", character_id=character_id):
            return False
        if self._chat_api is None:
            logger.warning("[InitiativeAction] ChatAPI недоступен")
            return False
        # Доставка в запущенную Unity-игру требует поддержки на стороне мода
        # (Unity создаёт задачу по своему запросу; внешняя задача из Python ей
        # неизвестна). Пока такой поддержки нет — инициатива идёт в обычный чат.
        task_uid = None
        try:
            ok = self._chat_api.initiate(
                character_id=character_id,
                instruction=str(instruction or ""),
                sender="System",
                task_uid=task_uid,
            )
            return bool(ok)
        except Exception as exc:
            logger.warning("[InitiativeAction] initiate_dialogue failed: %s", exc)
            return False

    # -------------------------------------------------------------- tools

    def execute_tool(
        self, character_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> str:
        """Выполнить инструмент через ToolManager, если разрешено."""
        if not self._policy.can_execute(tool_name, character_id=character_id):
            return f"[InitiativeAction] инструмент '{tool_name}' запрещён политикой"
        if self._tool_manager is None:
            return "[InitiativeAction] ToolManager недоступен"
        try:
            result = self._tool_manager.run(tool_name, arguments or {})
            return str(result)
        except Exception as exc:
            logger.warning("[InitiativeAction] tool %s failed: %s", tool_name, exc)
            return f"[InitiativeAction] ошибка: {exc}"

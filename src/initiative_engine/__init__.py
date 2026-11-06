"""Initiative Engine для NeuroMita.

Отдельная подсистема, которая даёт персонажу самостоятельное поведение:
наблюдение за окружением, формирование намерений и принятие решений о том,
когда заговорить, действовать или промолчать. Минимально вмешивается в
существующий код NeuroMita и использует его инфраструктуру (ChatAPI,
ToolManager, Memory/RAG, MCP).
"""

from .config import InitiativeConfig
from .engine import InitiativeEngine

__all__ = [
    "InitiativeConfig",
    "InitiativeEngine",
]

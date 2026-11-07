"""Этап 3: состояние взаимодействия с пользователем и Initiative Gate.
Этап 7: характер-ориентированная реакция на сигналы (ReactionPolicy)."""
from .initiative_gate import InitiativeGate
from .reaction_policy import ReactionPolicy, TraitsProfile
from .user_interaction_state import UserInteractionState

__all__ = ["InitiativeGate", "ReactionPolicy", "TraitsProfile", "UserInteractionState"]

# app/session_state.py
# Session and conversation state helpers

from dataclasses import dataclass, field


class RollingConversationMemory:
    def __init__(self, max_turns: int = 4):
        self.max_turns = max_turns
        self.history = []

    def add_turn(self, user_message: str, assistant_message: str):
        self.history.append(
            {
                "user": user_message,
                "assistant": assistant_message,
            }
        )
        self.history = self.history[-self.max_turns :]

    def format_history(self) -> str:
        if not self.history:
            return "No previous conversation."

        formatted = []
        for i, turn in enumerate(self.history, start=1):
            formatted.append(f"Turn {i} - User: {turn['user']}")
            formatted.append(f"Turn {i} - Assistant: {turn['assistant']}")

        return "\n".join(formatted)


@dataclass
class ChatSessionState:
    mode: str = "normal"  # normal | escalation
    memory: RollingConversationMemory = field(
        default_factory=lambda: RollingConversationMemory(max_turns=4)
    )
    incident_state: object | None = None
    logs: list = field(default_factory=list)
    pending_incident_field: str | None = None

    def log_turn(self, user_message: str, bot_message: str, route_type: str):
        self.logs.append(
            {
                "user_message": user_message,
                "bot_message": bot_message,
                "route_type": route_type,
            }
        )


def create_empty_chat_session_state() -> ChatSessionState:
    """
    Fallback session factory used before the full backend is wired.
    """
    return ChatSessionState()

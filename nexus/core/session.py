"""Conversation and Session Management for NEXUS.

Maintains multi-turn context, session history, and provides clear boundaries
between ephemeral conversation state and persistent Hermes memory.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus.core.session")


@dataclass
class ChatMessage:
    """A single message in a conversation session."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:10]}")
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConversationSession:
    """An active conversation session tracking history and context."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        max_history_turns: int = 20,
    ) -> None:
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self.title = title or f"Conversation {datetime.datetime.now().strftime('%b %d, %H:%M')}"
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.max_history_turns = max_history_turns
        self.messages: List[ChatMessage] = []

    def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ChatMessage:
        """Append a new message to the session."""
        msg = ChatMessage(role=role, content=content, metadata=metadata or {})
        self.messages.append(msg)
        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Enforce memory-bounded conversation window
        if len(self.messages) > self.max_history_turns * 2:
            # Preserve initial system prompt if present, truncate older turns
            has_system = self.messages[0].role == "system"
            sys_msg = self.messages[0] if has_system else None
            recent = self.messages[-(self.max_history_turns * 2):]
            if has_system and recent[0].role != "system":
                self.messages = [sys_msg] + recent
            else:
                self.messages = recent

        return msg

    def get_context_messages(self) -> List[Dict[str, Any]]:
        """Return messages in standard chat completion format."""
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def clear(self) -> None:
        """Clear session messages."""
        self.messages.clear()
        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()


class SessionManager:
    """Manages active and historical conversation sessions."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self._sessions: Dict[str, ConversationSession] = {}
        self._active_session_id: Optional[str] = None

        # Create default session
        default_session = self.create_session("New Chat")
        self._active_session_id = default_session.session_id

    def create_session(self, title: Optional[str] = None) -> ConversationSession:
        """Create and activate a new conversation session."""
        sess = ConversationSession(title=title)
        self._sessions[sess.session_id] = sess
        self._active_session_id = sess.session_id
        return sess

    def get_active_session(self) -> ConversationSession:
        """Return current active session or create one."""
        if not self._active_session_id or self._active_session_id not in self._sessions:
            return self.create_session()
        return self._sessions[self._active_session_id]

    def set_active_session(self, session_id: str) -> bool:
        """Switch active session."""
        if session_id in self._sessions:
            self._active_session_id = session_id
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions with summary metadata."""
        return [
            {
                "session_id": s.session_id,
                "title": s.title,
                "message_count": len(s.messages),
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "is_active": s.session_id == self._active_session_id,
            }
            for s in self._sessions.values()
        ]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            if self._active_session_id == session_id:
                self._active_session_id = next(iter(self._sessions.keys())) if self._sessions else None
            return True
        return False


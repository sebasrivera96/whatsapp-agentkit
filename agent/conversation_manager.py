# agent/conversation_manager.py — Estado de conversación por cliente
# Portado de SICAS_AI/conversation_manager.py

"""
Mantiene un ConversationState por número de teléfono en memoria.
El estado incluye: historial de mensajes (formato Claude API), modo del bot
(ai/paused), contexto del cliente identificado y cliente SICAS.
"""

import time
import os
from dataclasses import dataclass, field

from agent.sicas_client import SICASClient


@dataclass
class ConversationState:
    phone: str
    messages: list[dict] = field(default_factory=list)
    mode: str = "ai"                       # "ai" | "paused" | "closed"
    customer_context: dict | None = None   # {"id_cli": int, "nombre": str} una vez identificado
    last_activity: float = field(default_factory=time.time)
    sicas: SICASClient = field(repr=False, default=None)
    chat_id: str = ""                      # ID raw del chat (ej: "528111828879@s.whatsapp.net")
    warning_sent: bool = False             # True si ya se envió aviso de inactividad
    paused_msg_sent: bool = False          # True si ya se envió el mensaje de "asesor notificado"

    def append_user_message(self, text: str):
        """Agrega un mensaje del usuario al historial."""
        self.messages.append({"role": "user", "content": text})
        self.last_activity = time.time()
        self.warning_sent = False

    def trim_to_window(self, max_messages: int = 20):
        """Mantiene a lo sumo max_messages, preservando pares completos."""
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]


class ConversationManager:
    """Gestiona ConversationState por número de teléfono en memoria."""

    def __init__(self):
        self._states: dict[str, ConversationState] = {}
        self._sicas_base_url = os.getenv("SICAS_API_URL", "")
        self._sicas_username = os.getenv("SICAS_USERNAME", "")
        self._sicas_password = os.getenv("SICAS_PASSWORD", "")

    def get_or_create(self, phone: str) -> ConversationState:
        """Retorna el estado existente o crea uno nuevo para ese teléfono."""
        if phone not in self._states:
            self._states[phone] = ConversationState(
                phone=phone,
                sicas=SICASClient(
                    base_url=self._sicas_base_url,
                    username=self._sicas_username,
                    password=self._sicas_password,
                ),
            )
        return self._states[phone]

    def reset(self, phone: str):
        """Borra el estado de una conversación (útil para testing o reinicio)."""
        self._states.pop(phone, None)

    def set_mode(self, phone: str, mode: str):
        """Cambia el modo de un estado existente (no lo crea si no existe)."""
        if phone in self._states:
            self._states[phone].mode = mode

    def get_active_states(self) -> list["ConversationState"]:
        """Retorna estados con modo 'ai' (excluye paused y closed)."""
        return [s for s in self._states.values() if s.mode == "ai"]

    def close_session(self, phone: str):
        """Cierra una sesión: marca como closed y limpia historial."""
        if phone in self._states:
            state = self._states[phone]
            state.mode = "closed"
            state.messages.clear()
            state.customer_context = None

    def prune_inactive(self, max_age_seconds: int = 86400):
        """Elimina conversaciones inactivas por más de max_age_seconds (default: 24h)."""
        cutoff = time.time() - max_age_seconds
        to_delete = [p for p, s in self._states.items() if s.last_activity < cutoff]
        for phone in to_delete:
            del self._states[phone]

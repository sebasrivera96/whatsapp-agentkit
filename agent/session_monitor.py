# agent/session_monitor.py — Monitor de inactividad de sesiones
# Envía avisos y cierra sesiones por timeout

"""
Background task que revisa sesiones activas cada 15 segundos.
- A los 2.5 min de inactividad: envía aviso al cliente.
- A los 5 min de inactividad: cierra la sesión y notifica al cliente.
"""

import asyncio
import time
import logging
from typing import Callable, Awaitable

from agent.conversation_manager import ConversationManager

logger = logging.getLogger("agentkit")

# Timeouts en segundos
WARNING_TIMEOUT = 150   # 2.5 minutos
CLOSE_TIMEOUT = 300     # 5 minutos
SWEEP_INTERVAL = 15     # revisar cada 15 segundos


async def session_monitor_loop(
    manager: ConversationManager,
    send_message: Callable[[str, str], Awaitable[bool]],
    register_sent: Callable[[str, str], None],
    warning_message: str,
    close_message: str,
):
    """
    Loop que revisa periódicamente sesiones activas y gestiona timeouts.

    Args:
        manager: Gestor de conversaciones en memoria.
        send_message: Función async para enviar mensaje (proveedor.enviar_mensaje).
        register_sent: Función para registrar mensaje en cache anti-eco.
        warning_message: Texto del aviso de inactividad.
        close_message: Texto del cierre por timeout.
    """
    while True:
        await asyncio.sleep(SWEEP_INTERVAL)
        try:
            now = time.time()
            for state in manager.get_active_states():
                if not state.chat_id:
                    continue

                idle = now - state.last_activity

                if idle >= CLOSE_TIMEOUT:
                    # Cerrar sesión por inactividad
                    register_sent(state.chat_id, close_message)
                    await send_message(state.chat_id, close_message)
                    manager.close_session(state.phone)
                    logger.info(f"Sesión cerrada por inactividad: {state.phone}")

                elif idle >= WARNING_TIMEOUT and not state.warning_sent:
                    # Enviar aviso de inactividad
                    register_sent(state.chat_id, warning_message)
                    await send_message(state.chat_id, warning_message)
                    state.warning_sent = True
                    logger.info(f"Aviso de inactividad enviado: {state.phone}")

        except Exception as e:
            logger.error(f"Error en session monitor: {e}")

# agent/brain.py — Cerebro del agente: loop agentic con herramientas SICAS
# Integra SICAS_AI/ai_agent.py en el stack async de agentkit

"""
Lógica de IA del agente. Ejecuta un loop Claude con tool-use para:
- Buscar clientes y pólizas en SICAS
- Enviar documentos y formularios
- Escalar a asesores humanos

Retorna: (respuesta_para_cliente, mensaje_para_asesor | None)
"""

import os
import json
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.conversation_manager import ConversationState
from agent.tools import TOOLS, dispatch_tool

load_dotenv()
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _cargar_system_prompt() -> str:
    """Lee el system prompt desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            return config.get("system_prompt", "Eres un asistente útil. Responde en español.")
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return "Eres un asistente útil. Responde en español."


def _cargar_mensaje(clave: str, default: str) -> str:
    """Lee un mensaje de configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            return config.get(clave, default)
    except FileNotFoundError:
        return default


def _extract_text(content) -> str:
    """Extrae el texto de la lista de bloques de contenido de Claude."""
    parts = []
    for block in content:
        if hasattr(block, "type") and block.type == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
    return "\n".join(parts).strip()


async def generar_respuesta(
    state: ConversationState,
    form_urls: dict,
) -> tuple[str, str | None]:
    """
    Ejecuta el loop agentic de Claude con tool-use para un turno del usuario.

    Args:
        state: Estado actual de la conversación (historial, cliente identificado, cliente SICAS).
        form_urls: Dict con URLs de formularios PDF {"reembolso": "...", "procedimiento_medico": "..."}.

    Returns:
        Tupla (respuesta_cliente, mensaje_asesor).
        mensaje_asesor es None si no hubo escalación.
    """
    system = _cargar_system_prompt()

    # Inyectar contexto del cliente si ya fue identificado (evita volver a preguntar)
    if state.customer_context:
        nombre = state.customer_context.get("nombre", "")
        id_cli = state.customer_context.get("id_cli", "")
        system += (
            f"\n\n## Cliente identificado en esta sesión\n"
            f"Nombre: {nombre}\nIDCli: {id_cli}\n"
            f"No vuelvas a pedir su identidad."
        )

    error_msg = _cargar_mensaje(
        "error_message",
        "Lo sentimos, estamos experimentando dificultades técnicas. Por favor intente nuevamente en unos minutos."
    )

    for _ in range(10):  # safety cap — Claude raramente necesita más de 3-4 iteraciones
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system,
                messages=state.messages,
                tools=TOOLS,
            )
        except Exception as e:
            logger.error("Error Claude API: %s", e)
            return error_msg, None

        # Guardar respuesta completa (incluye bloques tool_use que Claude necesita en el siguiente turno)
        state.messages.append({"role": "assistant", "content": response.content})
        state.trim_to_window()

        if response.stop_reason == "end_turn":
            return _extract_text(response.content), None

        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                result = await dispatch_tool(block.name, block.input, state, form_urls)
                logger.info("Tool %s → %s", block.name, json.dumps(result, ensure_ascii=False)[:200])

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

                # No auto-identificamos al cliente aquí: la verificación de fecha de nacimiento
                # la realiza Claude siguiendo el system prompt. Claude llama a obtener_polizas
                # solo después de confirmar ambos factores (nombre + fecha), momento en el que
                # actualizamos customer_context desde el tool obtener_polizas.
                if block.name == "obtener_polizas" and "polizas" in result and not state.customer_context:
                    # Claude llegó a pedir las pólizas → identidad ya verificada
                    # Recuperar el nombre desde los mensajes anteriores si está disponible
                    state.customer_context = {
                        "id_cli": block.input.get("id_cli"),
                        "nombre": "",  # Se completará en el siguiente turno si Claude lo menciona
                    }
                    logger.info("Cliente verificado, IDCli=%s", block.input.get("id_cli"))

                # Escalación: pausar bot, retornar inmediatamente
                if block.name == "notificar_agente":
                    state.mode = "paused"
                    return result["mensaje_cliente"], result.get("mensaje_agente")

            state.messages.append({"role": "user", "content": tool_results})

    logger.warning("Loop agentic alcanzó el límite de iteraciones para %s", state.phone)
    return "Lo siento, no pude procesar su solicitud en este momento. Por favor intente de nuevo.", None

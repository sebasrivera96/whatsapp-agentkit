# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Integrado con SICAS CRM via ConversationManager

"""
Servidor principal del agente de WhatsApp de Gonzalez Loredo Asesoría Patrimonial.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
La IA usa tool-use para consultar pólizas en SICAS y escalar a asesores cuando sea necesario.
"""

import os
import time
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from agent.brain import generar_respuesta, _cargar_mensaje
from agent.memory import inicializar_db
from agent.conversation_manager import ConversationManager
from agent.providers import obtener_proveedor
from agent.session_monitor import session_monitor_loop

load_dotenv()

# Lista blanca de números autorizados (código de país, sin +)
NUMEROS_AUTORIZADOS = {
    "528111828879",
    "17378889040",
    # "528117403058",
    # "5218117403058",
    # "14253709886",
    # "5218181764764",
    "5218111828879",
}

# Números de auto-chat: responde aunque el mensaje sea "from_me"
SELF_CHAT_NUMEROS = {
    "17378889040",
}

# Configuración de logging
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

# Número del asesor para notificaciones de escalación
AGENT_WHATSAPP_NUMBER = os.getenv("AGENT_WHATSAPP_NUMBER", "")

# URLs de formularios PDF
# Si PUBLIC_URL está configurado, las rutas /forms/* se convierten en URLs absolutas.
# En desarrollo: http://localhost:8000/forms/...
# En Railway: https://tu-app.up.railway.app/forms/...
_PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
FORM_URLS = {
    "axa": {
        "reembolso":           f"{_PUBLIC_URL}/forms/AXA/solicitud_siniestros.pdf",
        "procedimiento_medico": f"{_PUBLIC_URL}/forms/AXA/solicitud_siniestros.pdf",
        "informe_medico":      f"{_PUBLIC_URL}/forms/AXA/informe_medico.pdf",
    },
    "seguros_monterrey": {
        "reembolso":               f"{_PUBLIC_URL}/forms/seguros_monterrey/solicitud_reembolso.pdf",
        "informe_medico":          f"{_PUBLIC_URL}/forms/seguros_monterrey/informe_medico.pdf",
        "aviso_accidente":         f"{_PUBLIC_URL}/forms/seguros_monterrey/aviso_accidente.pdf",
        "consentimiento_informado": f"{_PUBLIC_URL}/forms/seguros_monterrey/Consentimiento Informado_SMTNYL.pdf",
        "declaracion_veracidad":   f"{_PUBLIC_URL}/forms/seguros_monterrey/fomato-declaracion-de-veracidad.pdf",
    },
    "mapfre": {
        "reembolso":           f"{_PUBLIC_URL}/forms/Mapfre/solicitud_reembolso.pdf",
        "procedimiento_medico": f"{_PUBLIC_URL}/forms/Mapfre/solicitud_programacion.pdf",
        "informe_medico":      f"{_PUBLIC_URL}/forms/Mapfre/informe_medico.pdf",
        "aviso_accidente":     f"{_PUBLIC_URL}/forms/Mapfre/aviso_accidente.pdf",
        "kyc_siniestro":       f"{_PUBLIC_URL}/forms/Mapfre/kyc_siniestro.pdf",
    },
}

# ── Cache anti-bucle: registra mensajes enviados por el bot ──────────────────
_mensajes_enviados: dict[str, float] = {}
_DEDUP_TTL = 60  # ignorar ecos durante 60 segundos


def _msg_key(telefono: str, texto: str) -> str:
    """Genera clave única para un par (teléfono, texto)."""
    h = hashlib.md5(texto.encode()).hexdigest()
    return f"{telefono}:{h}"


def _registrar_enviado(telefono: str, texto: str):
    """Registra un mensaje enviado por el bot para evitar procesarlo como eco."""
    _mensajes_enviados[_msg_key(telefono, texto)] = time.time()
    # Limpiar entradas viejas
    ahora = time.time()
    for k in list(_mensajes_enviados):
        if ahora - _mensajes_enviados[k] > _DEDUP_TTL:
            del _mensajes_enviados[k]


def _es_eco(telefono: str, texto: str) -> bool:
    """Retorna True si el mensaje fue enviado recientemente por el bot."""
    ts = _mensajes_enviados.get(_msg_key(telefono, texto))
    return ts is not None and time.time() - ts < _DEDUP_TTL


# Mensaje cuando el bot está pausado (esperando asesor)
PAUSED_MSG = (
    "Su asesor ha sido notificado y estará con usted en breve. "
    "Si tiene alguna urgencia médica, contacte directamente a su aseguradora."
)

# Gestor de conversaciones en memoria (un estado por número de teléfono)
conversation_manager = ConversationManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa recursos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    sicas_url = os.getenv("SICAS_API_URL", "(no configurado)")
    logger.info(f"SICAS API: {sicas_url}")

    # Iniciar monitor de sesiones (timeouts por inactividad)
    warning_msg = _cargar_mensaje(
        "timeout_warning_message",
        "¿Sigue ahí? Esta sesión se cerrará en 2.5 minutos si no recibimos respuesta.",
    )
    close_msg = _cargar_mensaje(
        "timeout_close_message",
        "La sesión ha sido cerrada por inactividad. Si necesita más ayuda, envíenos un mensaje y con gusto le atendemos nuevamente.",
    )
    monitor_task = asyncio.create_task(
        session_monitor_loop(
            manager=conversation_manager,
            send_message=proveedor.enviar_mensaje,
            register_sent=_registrar_enviado,
            warning_message=warning_msg,
            close_message=close_msg,
        )
    )
    logger.info("Session monitor iniciado")

    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Soporte GL Asesoría Patrimonial — WhatsApp AI Agent",
    version="2.0.0",
    lifespan=lifespan
)

# Servir formularios PDF como archivos estáticos en /forms/*
app.mount("/forms", StaticFiles(directory="forms"), name="forms")


@app.get("/")
async def health_check():
    return {"status": "ok", "service": "Soporte GL Asesoría Patrimonial"}


@app.get("/webhook")
@app.get("/webhook/messages")
@app.get("/webhook/messages/post")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook/chats/post")
@app.post("/webhook/statuses/post")
async def webhook_eventos_ignorados(request: Request):
    """Recibe eventos de Whapi que no requieren procesamiento (chats, statuses)."""
    return {"status": "ok"}


@app.post("/webhook")
@app.post("/webhook/messages")
@app.post("/webhook/messages/post")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje con el loop agentic SICAS y envía respuesta.
    """
    try:
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            if not msg.texto:
                continue

            # Normalizar número de teléfono
            numero_limpio = msg.telefono.replace("+", "").replace("@s.whatsapp.net", "").split("@")[0]

            # Ignorar mensajes propios excepto auto-chat autorizado
            if msg.es_propio and numero_limpio not in SELF_CHAT_NUMEROS:
                logger.debug(f"Ignorado (from_me): {msg.telefono}")
                continue

            # Anti-bucle: ignorar ecos de mensajes que el bot envió
            if _es_eco(msg.telefono, msg.texto):
                logger.debug(f"Ignorado (eco detectado): {msg.telefono}")
                continue

            # Verificar lista blanca
            if numero_limpio not in NUMEROS_AUTORIZADOS:
                logger.info(f"Número no autorizado ignorado: {msg.telefono}")
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Obtener o crear estado de conversación
            state = conversation_manager.get_or_create(numero_limpio)
            state.chat_id = msg.telefono

            # Si la sesión fue cerrada, iniciar una nueva
            if state.mode == "closed":
                conversation_manager.reset(numero_limpio)
                state = conversation_manager.get_or_create(numero_limpio)
                state.chat_id = msg.telefono

            # Si el bot está pausado (esperando asesor), enviar mensaje de espera
            if state.mode == "paused":
                _registrar_enviado(msg.telefono, PAUSED_MSG)
                await proveedor.enviar_mensaje(msg.telefono, PAUSED_MSG)
                continue

            # Agregar mensaje del usuario al historial
            state.append_user_message(msg.texto)

            # Generar respuesta con loop agentic SICAS
            respuesta, msg_asesor = await generar_respuesta(state, FORM_URLS)

            # Notificar al asesor si hubo escalación
            if msg_asesor and AGENT_WHATSAPP_NUMBER:
                notif_asesor = f"📞 Cliente: {msg.telefono}\n{msg_asesor}"
                await proveedor.enviar_mensaje(AGENT_WHATSAPP_NUMBER, notif_asesor)
                logger.info(f"Asesor notificado ({AGENT_WHATSAPP_NUMBER}): {msg_asesor}")

            # Registrar en cache anti-bucle ANTES de enviar
            _registrar_enviado(msg.telefono, respuesta)

            # Enviar respuesta al cliente
            await proveedor.enviar_mensaje(msg.telefono, respuesta)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

            # Si el agente cerró la sesión (cerrar_sesion tool), limpiar estado
            if state.mode == "closed":
                logger.info(f"Sesión cerrada por el cliente: {numero_limpio}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints administrativos ─────────────────────────────────────────────────

@app.post("/admin/reset/{phone}")
async def admin_reset(phone: str):
    """Borra el estado de conversación de un número (reinicio completo)."""
    conversation_manager.reset(phone)
    logger.info(f"Conversación reiniciada para: {phone}")
    return {"status": "ok", "phone": phone, "action": "reset"}


@app.post("/admin/unpause/{phone}")
async def admin_unpause(phone: str):
    """Reactiva el bot para un número que estaba pausado (post-escalación)."""
    conversation_manager.set_mode(phone, "ai")
    logger.info(f"Bot reactivado para: {phone}")
    return {"status": "ok", "phone": phone, "action": "unpause"}

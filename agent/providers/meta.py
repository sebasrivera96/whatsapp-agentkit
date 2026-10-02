# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import hmac
import hashlib
import logging
import httpx
from fastapi import Request, HTTPException
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")

# Límite de caracteres de un mensaje de texto en la Cloud API
_MAX_TEXTO = 4096


def normalizar_numero_mx(telefono: str) -> str:
    """
    Meta entrega los números mexicanos con el "1" legado (521 + 10 dígitos),
    pero al ENVIAR rechaza ese formato: hay que mandar 52 + 10 dígitos.
    """
    numero = telefono.replace("+", "").strip()
    if numero.startswith("521") and len(numero) == 13:
        return "52" + numero[3:]
    return numero


def _partir_texto(texto: str, limite: int = _MAX_TEXTO) -> list[str]:
    """Divide un texto largo en partes que respeten el límite de Meta, cortando en saltos de línea."""
    partes = []
    while len(texto) > limite:
        corte = texto.rfind("\n", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(texto[:corte])
        texto = texto[corte:].lstrip("\n")
    if texto:
        partes.append(texto)
    return partes


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        # App Secret (App Settings → Basic): firma cada webhook con X-Hub-Signature-256
        self.app_secret = os.getenv("META_APP_SECRET", "")
        self.api_version = os.getenv("META_API_VERSION", "v21.0")

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Meta requiere verificación GET con hub.verify_token."""
        params = request.query_params
        mode = params.get("hub.mode")
        if mode is None:
            return None  # no es una verificación de Meta (p. ej. health check)
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")
        if mode == "subscribe" and hmac.compare_digest(token, self.verify_token):
            # Meta espera el challenge tal cual, en texto plano
            return challenge
        logger.warning("Verificación de webhook de Meta rechazada: verify token no coincide")
        raise HTTPException(status_code=403, detail="Forbidden")

    async def webhook_autorizado(self, request: Request) -> bool:
        """Valida la firma HMAC-SHA256 (X-Hub-Signature-256) que Meta agrega a cada webhook."""
        if not self.app_secret:
            logger.warning("META_APP_SECRET no configurado — firma del webhook NO verificada")
            return True
        firma = request.headers.get("X-Hub-Signature-256", "")
        body = await request.body()
        esperada = "sha256=" + hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(firma, esperada)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload anidado de Meta Cloud API. Ignora 'statuses' (entregado/leído)."""
        body = await request.json()
        mensajes = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    tipo = msg.get("type")
                    if tipo == "text":
                        texto = msg.get("text", {}).get("body", "")
                    elif tipo == "button":
                        texto = msg.get("button", {}).get("text", "")
                    elif tipo == "interactive":
                        interactivo = msg.get("interactive", {})
                        respuesta = interactivo.get("button_reply") or interactivo.get("list_reply") or {}
                        texto = respuesta.get("title", "")
                    else:
                        logger.info(f"Mensaje tipo '{tipo}' de {msg.get('from')} ignorado (solo se procesa texto)")
                        continue
                    mensajes.append(MensajeEntrante(
                        telefono=msg.get("from", ""),
                        texto=texto,
                        mensaje_id=msg.get("id", ""),
                        es_propio=False,  # Meta solo envía mensajes entrantes
                    ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via Meta WhatsApp Cloud API."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        destino = normalizar_numero_mx(telefono)
        exito = True
        # timeout explícito: un cuelgue de Meta no debe bloquear el handler del webhook
        async with httpx.AsyncClient(timeout=10) as client:
            for parte in _partir_texto(mensaje):
                payload = {
                    "messaging_product": "whatsapp",
                    "to": destino,
                    "type": "text",
                    "text": {"body": parte},
                }
                r = await client.post(url, json=payload, headers=headers)
                # Un 200 solo significa "aceptado", no "entregado" (ver statuses en el webhook)
                if r.status_code != 200:
                    logger.error(f"Error Meta API: {r.status_code} — {r.text}")
                    exito = False
                    break
        return exito

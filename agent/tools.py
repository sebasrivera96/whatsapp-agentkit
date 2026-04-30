# agent/tools.py — Herramientas SICAS para el agente de WhatsApp
# Portado de SICAS_AI/ai_agent.py

"""
Define las 5 herramientas que Claude puede invocar y el dispatcher async
que ejecuta cada llamada contra el CRM SICAS.
"""

import logging
import yaml
from agent.conversation_manager import ConversationState

logger = logging.getLogger("agentkit")


def _cargar_forms_config() -> dict:
    """Carga la configuración de formularios desde config/forms.yaml."""
    try:
        with open("config/forms.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/forms.yaml no encontrado")
        return {}


def _normalizar_compania(compania_input: str) -> str:
    """Normaliza el nombre de la compañía a su clave interna."""
    compania_input = compania_input.lower()
    if "monterrey" in compania_input or "smnyl" in compania_input:
        return "seguros_monterrey"
    elif "axa" in compania_input:
        return "axa"
    elif "mapfre" in compania_input:
        return "mapfre"
    return compania_input

# ── Definiciones de herramientas para la Claude API ──────────────────────────

TOOLS = [
    {
        "name": "buscar_cliente",
        "description": (
            "Busca clientes en el sistema SICAS por nombre o apellido. "
            "Úsala cuando el cliente mencione su nombre o pida información de sus pólizas. "
            "Devuelve una lista de clientes con IDCli y NombreCompleto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre o apellido a buscar. Ej: 'Olavarrieta' o 'Jorge Olavarrieta'.",
                }
            },
            "required": ["nombre"],
        },
    },
    {
        "name": "obtener_polizas",
        "description": (
            "Obtiene todas las pólizas de un cliente dado su IDCli. "
            "Usar después de confirmar la identidad del cliente con buscar_cliente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_cli": {
                    "type": "integer",
                    "description": "ID del cliente en SICAS, obtenido de buscar_cliente.",
                }
            },
            "required": ["id_cli"],
        },
    },
    {
        "name": "obtener_documento",
        "description": (
            "Obtiene el enlace de descarga del documento digital de una póliza. "
            "Usar cuando el cliente pida su póliza, comprobante o documento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_docto": {
                    "type": "integer",
                    "description": "ID del documento en SICAS, obtenido de obtener_polizas.",
                },
                "numero_poliza": {
                    "type": "string",
                    "description": "Número de póliza legible (campo Documento), para mostrarlo al cliente.",
                },
            },
            "required": ["id_docto", "numero_poliza"],
        },
    },
    {
        "name": "obtener_formularios",
        "description": (
            "Devuelve los formularios PDF necesarios para un trámite de seguro. "
            "El sistema determina automáticamente qué formularios entregar (puede ser más de uno). "
            "Confirma la compañía y el tipo de trámite antes de llamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "compania": {
                    "type": "string",
                    "enum": ["axa", "seguros_monterrey", "mapfre"],
                    "description": "Aseguradora del cliente (de CiaNombre o lo que el cliente indique).",
                },
                "escenario": {
                    "type": "string",
                    "enum": [
                        "reembolso",
                        "reembolso_con_declaracion",
                        "cirugia",
                        "informe_medico",
                        "accidente",
                        "accidente_con_kyc",
                    ],
                    "description": (
                        "'reembolso': cliente YA pagó y quiere reembolso. "
                        "'reembolso_con_declaracion': reembolso + declaración de veracidad (si la aseguradora lo pide). "
                        "'cirugia': cliente VA A operarse, necesita autorización previa. "
                        "'informe_medico': el médico tratante debe llenar un informe. "
                        "'accidente': notificación de accidente. "
                        "'accidente_con_kyc': accidente + verificación KYC (Mapfre)."
                    ),
                },
            },
            "required": ["compania", "escenario"],
        },
    },
    {
        "name": "notificar_agente",
        "description": (
            "Notifica a un asesor humano y pausa el bot para esa conversación. "
            "Usar cuando: el cliente está molesto, menciona siniestro/accidente/urgente, "
            "pide hablar con una persona, solicita cancelación o modificación de póliza, "
            "o no se puede encontrar al cliente después de 2 intentos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "razon": {
                    "type": "string",
                    "description": "Motivo breve de la escalación para informar al asesor.",
                },
                "urgencia": {
                    "type": "string",
                    "enum": ["normal", "urgente"],
                    "description": "Nivel de urgencia.",
                },
            },
            "required": ["razon", "urgencia"],
        },
    },
    {
        "name": "cerrar_sesion",
        "description": (
            "Cierra la sesión de conversación con el cliente. "
            "Usar ÚNICAMENTE cuando el cliente indique explícitamente que no necesita más ayuda, "
            "por ejemplo: 'eso es todo', 'no gracias', 'ya no necesito nada', 'muchas gracias, eso sería todo'. "
            "IMPORTANTE: Despídete del cliente en tu mensaje de texto ANTES de llamar esta herramienta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Breve descripción de por qué se cierra (ej: 'cliente indicó que no necesita más ayuda').",
                },
            },
            "required": ["motivo"],
        },
    },
]


# ── Dispatcher async ──────────────────────────────────────────────────────────

async def dispatch_tool(name: str, inputs: dict, state: ConversationState, form_urls: dict) -> dict:
    """Ejecuta una herramienta y retorna el resultado como dict."""

    if name == "buscar_cliente":
        nombre = inputs.get("nombre", "")
        try:
            clientes = await state.sicas.search_customers(nombre)
        except Exception as e:
            logger.error("buscar_cliente error: %s", e)
            return {"error": "No se pudo conectar con el sistema. Intenta más tarde."}

        if not clientes:
            return {"clientes": [], "total": 0, "mensaje": f"No se encontraron clientes con el nombre '{nombre}'."}

        resumen = [
            {
                "IDCli": c.get("IDCli"),
                "NombreCompleto": c.get("NombreCompleto", ""),
                "RFC": c.get("RFC", ""),
                "FechaNac": c.get("FechaNac", ""),  # Para verificación de identidad — no mostrar al cliente
            }
            for c in clientes[:5]
        ]
        return {"clientes": resumen, "total": len(resumen)}

    if name == "obtener_polizas":
        id_cli = inputs.get("id_cli")
        try:
            polizas = await state.sicas.get_policies(id_cli)
        except Exception as e:
            logger.error("obtener_polizas error: %s", e)
            return {"error": "No se pudo obtener las pólizas. Intenta más tarde."}

        if not polizas:
            return {"polizas": [], "total": 0, "mensaje": "Este cliente no tiene pólizas registradas."}

        resumen = [
            {
                "IDDocto": p.get("IDDocto"),
                "Documento": p.get("Documento", ""),
                "CiaNombre": p.get("CiaNombre", ""),
                "SRamoNombre": p.get("SRamoNombre", ""),
                "FDesde": p.get("FDesde", ""),
                "FHasta": p.get("FHasta", ""),
                "Status_TXT": p.get("Status_TXT", ""),
            }
            for p in polizas
        ]
        return {"polizas": resumen, "total": len(resumen)}

    if name == "obtener_documento":
        id_docto = inputs.get("id_docto")
        numero_poliza = inputs.get("numero_poliza", "")
        try:
            archivos = await state.sicas.get_policy_document_link(id_docto)
        except Exception as e:
            logger.error("obtener_documento error: %s", e)
            return {"error": "No se pudo obtener el documento. Intenta más tarde."}

        if not archivos:
            return {
                "archivos": [],
                "mensaje": (
                    f"La póliza {numero_poliza} no tiene documentos digitales disponibles. "
                    "Es posible que el documento aún no haya sido subido al sistema."
                ),
            }

        enlaces = [
            {
                "nombre": f"{f.get('FileName', 'documento')}.{f.get('Ext', 'pdf')}",
                "url": f.get("PathWWW", ""),
                "tamaño": f.get("SizeFile", ""),
            }
            for f in archivos
        ]
        return {"poliza": numero_poliza, "archivos": enlaces}

    if name == "obtener_formularios":
        compania_key = _normalizar_compania(inputs.get("compania", ""))
        escenario = inputs.get("escenario", "")

        config = _cargar_forms_config()
        escenario_config = config.get("escenarios", {}).get(escenario)

        if not escenario_config:
            return {"error": f"Escenario '{escenario}' no reconocido. Contacte a su asesor."}

        compania_info = config.get("companias", {}).get(compania_key, {})
        compania_display = compania_info.get("nombre_display", compania_key)

        formularios_ids = escenario_config.get("formularios_por_compania", {}).get(compania_key)

        if formularios_ids is None:
            return {
                "error": f"Este trámite no está disponible para {compania_display}. Escale al asesor.",
                "escalar": True,
            }

        formularios_catalog = config.get("formularios", {})
        urls_compania = form_urls.get(compania_key, {})
        resultados = []
        for form_id in formularios_ids:
            url = urls_compania.get(form_id)
            nombre = formularios_catalog.get(form_id, {}).get("nombre", form_id)
            if url:
                resultados.append({"tipo": form_id, "nombre": nombre, "url": url})
            else:
                resultados.append({"tipo": form_id, "nombre": nombre, "error": "URL no disponible"})

        return {
            "compania": compania_display,
            "escenario": escenario,
            "total_formularios": len(resultados),
            "formularios": resultados,
            "instruccion": f"Entregar TODOS los {len(resultados)} formularios al cliente.",
        }

    if name == "notificar_agente":
        razon = inputs.get("razon", "")
        urgencia = inputs.get("urgencia", "normal")
        return {
            "razon": razon,
            "urgencia": urgencia,
            "mensaje_cliente": (
                "Entendido. Voy a conectarle con uno de nuestros asesores para que le ayude. "
                "En breve se pondrán en contacto con usted. 🙏"
            ),
            "mensaje_agente": (
                f"{'🚨 URGENTE' if urgencia == 'urgente' else '🔔 Atención requerida'}\n"
                f"Motivo: {razon}"
            ),
        }

    if name == "cerrar_sesion":
        motivo = inputs.get("motivo", "")
        logger.info(f"Sesión cerrada por herramienta: {motivo}")
        return {
            "cerrar": True,
            "motivo": motivo,
            "mensaje_cliente": (
                "Gracias por comunicarse con Gonzalez Loredo Asesoría Patrimonial. "
                "¡Que tenga excelente día! Si necesita algo más en el futuro, no dude en escribirnos."
            ),
        }

    return {"error": f"Herramienta desconocida: {name}"}

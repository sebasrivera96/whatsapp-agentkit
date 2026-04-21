# agent/tools.py — Herramientas SICAS para el agente de WhatsApp
# Portado de SICAS_AI/ai_agent.py

"""
Define las 5 herramientas que Claude puede invocar y el dispatcher async
que ejecuta cada llamada contra el CRM SICAS.
"""

import logging
from agent.conversation_manager import ConversationState

logger = logging.getLogger("agentkit")

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
        "name": "obtener_formulario",
        "description": (
            "Devuelve el enlace al formulario PDF de la aseguradora correcta. "
            "SIEMPRE especificar la compañía del cliente. "
            "Para programación de cirugía (AXA), llamar DOS veces: 'procedimiento_medico' e 'informe_medico'. "
            "Si no sabes la compañía, pregunta al cliente antes de llamar este tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo_formulario": {
                    "type": "string",
                    "enum": [
                        "reembolso",
                        "procedimiento_medico",
                        "informe_medico",
                        "aviso_accidente",
                        "consentimiento_informado",
                        "declaracion_veracidad",
                        "kyc_siniestro",
                    ],
                    "description": (
                        "'reembolso': cliente YA pagó y quiere que la aseguradora le reembolse. "
                        "'procedimiento_medico': cliente VA A operarse, necesita autorización previa (AXA y Mapfre). "
                        "'informe_medico': el médico tratante llena un informe clínico (AXA, Seguros Monterrey y Mapfre). "
                        "'aviso_accidente': notificación de accidente (Seguros Monterrey y Mapfre). "
                        "'consentimiento_informado': consentimiento informado del paciente antes de un procedimiento médico (solo Seguros Monterrey). "
                        "'declaracion_veracidad': declaración de veracidad que acompaña solicitudes de reembolso (solo Seguros Monterrey). "
                        "'kyc_siniestro': formulario KYC (Know Your Customer) para verificación de identidad en siniestros (solo Mapfre)."
                    ),
                },
                "compania": {
                    "type": "string",
                    "enum": ["axa", "seguros_monterrey", "mapfre"],
                    "description": (
                        "Aseguradora del cliente. Determinada por el campo CiaNombre de la póliza "
                        "o por lo que el cliente mencione. "
                        "'axa' para AXA Seguros. "
                        "'seguros_monterrey' para Seguros Monterrey New York Life (SMNYL). "
                        "'mapfre' para Mapfre Seguros."
                    ),
                },
            },
            "required": ["tipo_formulario", "compania"],
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

    if name == "obtener_formulario":
        tipo = inputs.get("tipo_formulario")
        compania_input = inputs.get("compania", "").lower()

        # Normalizar nombre de compañía a clave interna
        if "monterrey" in compania_input or "smnyl" in compania_input:
            compania_key = "seguros_monterrey"
        elif "axa" in compania_input:
            compania_key = "axa"
        elif "mapfre" in compania_input:
            compania_key = "mapfre"
        else:
            compania_key = compania_input

        urls_compania = form_urls.get(compania_key, {})
        url = urls_compania.get(tipo)

        if not url:
            compania_nombre = {
                "axa": "AXA",
                "seguros_monterrey": "Seguros Monterrey New York Life",
                "mapfre": "Mapfre Seguros",
            }.get(compania_key, compania_key)
            return {"error": f"El formulario '{tipo}' no está disponible para {compania_nombre}. Contacte a su asesor."}

        nombres = {
            "reembolso":               "Formulario de Reembolso de Gastos Médicos",
            "procedimiento_medico":    "Formulario de Solicitud de Programación / Procedimiento Médico",
            "informe_medico":          "Informe Médico",
            "aviso_accidente":         "Aviso de Accidente",
            "consentimiento_informado": "Consentimiento Informado",
            "declaracion_veracidad":   "Formato de Declaración de Veracidad",
            "kyc_siniestro":           "Formulario KYC — Siniestro General",
        }
        compania_display = {
            "axa": "AXA",
            "seguros_monterrey": "Seguros Monterrey New York Life",
            "mapfre": "Mapfre Seguros",
        }.get(compania_key, compania_key)
        return {"tipo": tipo, "compania": compania_display, "nombre": nombres.get(tipo, tipo), "url": url}

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

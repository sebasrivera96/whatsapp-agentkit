# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas de Gonzalez Loredo Asesoría Patrimonial.
Estas funciones extienden las capacidades del agente más allá de responder texto.
"""

import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio y si está abierto en este momento."""
    info = cargar_info_negocio()
    horario = info.get("negocio", {}).get("horario", "Lunes a Sábado de 9:00 AM a 6:00 PM")

    # Calcular si está dentro del horario actual (hora de México)
    ahora = datetime.now()
    dia_semana = ahora.weekday()  # 0=Lunes, 6=Domingo
    hora_actual = ahora.hour

    # Lunes (0) a Sábado (5), de 9 a 18
    esta_abierto = (dia_semana <= 5) and (9 <= hora_actual < 18)

    return {
        "horario": horario,
        "esta_abierto": esta_abierto,
        "dia_actual": ahora.strftime("%A"),
        "hora_actual": ahora.strftime("%H:%M"),
    }


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge.
    Retorna el contenido más relevante encontrado.
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                # Búsqueda simple por coincidencia de texto
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


def obtener_info_reembolso() -> str:
    """
    Retorna los pasos y documentos necesarios para iniciar un reembolso.
    Esta información se incluye en la respuesta del agente cuando el cliente pregunta por reembolsos.
    """
    return """
Para iniciar un reembolso de gastos médicos necesita:

1. Formato de reembolso de su aseguradora (le ayudamos a obtenerlo)
2. Facturas originales o CFDI de los gastos médicos
3. Recetas médicas correspondientes
4. Resumen médico o estudios de laboratorio (según aplique)
5. Identificación oficial (INE o pasaporte)
6. Estado de cuenta bancario para el depósito del reembolso

El tiempo de respuesta varía según la aseguradora, generalmente entre 10 y 30 días hábiles.

Para iniciar el proceso, contacte a su asesor en Gonzalez Loredo Asesoría Patrimonial con su número de póliza.
""".strip()


def obtener_info_programacion_medica() -> str:
    """
    Retorna los pasos para solicitar una programación médica con red de proveedores.
    """
    return """
Para agendar una consulta o procedimiento médico con la red de proveedores:

1. Contáctenos con al menos 48 horas de anticipación
2. Tenga a la mano:
   - Nombre completo del paciente
   - Número de póliza
   - Tipo de consulta o procedimiento requerido
   - Especialidad médica o médico de su preferencia
   - Ciudad y fecha preferida
3. Nuestro equipo gestionará la autorización con su aseguradora
4. Le confirmaremos el proveedor en red y los detalles de la cita

Recuerde: para emergencias médicas, contacte directamente la línea de emergencias de su aseguradora.
""".strip()

# Skill: setup-forms
# Sincroniza los formularios PDF disponibles en forms/ con tools.py, main.py y prompts.yaml.
# Ejecutar después de agregar o cambiar PDFs de aseguradoras.

Eres el asistente de configuración de formularios para el agente de WhatsApp (AgentKit).
Tu tarea es sincronizar automáticamente los PDFs disponibles en `forms/` con los tres archivos
que los referencian: `agent/main.py`, `agent/tools.py` y `config/prompts.yaml`.

---

## PASO 1 — Descubrir formularios disponibles

Usa Glob para listar todos los PDFs en `forms/**/*.pdf`.

Agrupa los resultados por directorio (compañía). Para cada directorio:
- Usa el nombre del directorio como clave interna (en minúsculas). Ejemplos:
  - `AXA/` → `axa`
  - `seguros_monterrey/` → `seguros_monterrey`
  - `Mapfre/` → `mapfre`
- Para cada PDF en ese directorio, infiere el tipo de formulario por el nombre del archivo:
  - contiene `reembolso` o `siniestro` → `reembolso`
  - contiene `procedimiento` → `procedimiento_medico`
  - contiene `informe` → `informe_medico`
  - contiene `accidente` o `aviso` → `aviso_accidente`
  - si no coincide con ninguno → muestra advertencia y omite ese archivo (pide al desarrollador renombrarlo)

Muestra el catálogo descubierto antes de hacer cambios:
```
Formularios encontrados:
  axa:
    reembolso → AXA/solicitud_siniestros.pdf
    informe_medico → AXA/informe_medico.pdf
  seguros_monterrey:
    reembolso → seguros_monterrey/solicitud_reembolso.pdf
    ...
  [directorio vacío: Mapfre — sin PDFs, se omite]
```

Si NO hay ningún PDF en `forms/`, muestra un error y detente:
```
Error: No se encontraron PDFs en forms/. Agrega los formularios de las aseguradoras antes de ejecutar este skill.
```

---

## PASO 2 — Actualizar `agent/main.py`

Lee `agent/main.py` y localiza el bloque `FORM_URLS = { ... }`.

Reemplázalo con uno generado desde el catálogo descubierto en el Paso 1.
Formato a usar:
```python
FORM_URLS = {
    "axa": {
        "reembolso":            f"{_PUBLIC_URL}/forms/AXA/solicitud_siniestros.pdf",
        "procedimiento_medico": f"{_PUBLIC_URL}/forms/AXA/solicitud_siniestros.pdf",
        "informe_medico":       f"{_PUBLIC_URL}/forms/AXA/informe_medico.pdf",
    },
    "seguros_monterrey": {
        "reembolso":       f"{_PUBLIC_URL}/forms/seguros_monterrey/solicitud_reembolso.pdf",
        "informe_medico":  f"{_PUBLIC_URL}/forms/seguros_monterrey/informe_medico.pdf",
        "aviso_accidente": f"{_PUBLIC_URL}/forms/seguros_monterrey/aviso_accidente.pdf",
    },
    # Agrega aquí las nuevas compañías descubiertas
}
```

Reglas:
- Para cada compañía y tipo, usa la ruta real del archivo descubierto.
- Mantén `_PUBLIC_URL` como variable (NO hardcodees la URL).
- Preserva todo lo demás del archivo sin cambios.
- **Excepción AXA:** si `procedimiento_medico` no existe como archivo separado pero sí `reembolso`,
  apunta `procedimiento_medico` al mismo PDF que `reembolso` (es el comportamiento actual de AXA).

---

## PASO 3 — Actualizar `agent/tools.py`

Lee `agent/tools.py` y realiza TRES cambios:

### 3a. Enum `compania` en la definición de la herramienta `obtener_formulario`

Localiza el campo `"compania"` dentro de `TOOLS` → `obtener_formulario` → `input_schema`.
Actualiza:
- `"enum"`: agrega las claves de las nuevas compañías descubiertas.
- `"description"`: agrega una línea por cada nueva compañía con su clave y nombre de display.

Ejemplo si se agrega Mapfre:
```python
"enum": ["axa", "seguros_monterrey", "mapfre"],
"description": (
    "Aseguradora del cliente. ..."
    "'axa' para AXA Seguros. "
    "'seguros_monterrey' para Seguros Monterrey New York Life (SMNYL). "
    "'mapfre' para Mapfre Seguros."
),
```

### 3b. Bloque de normalización en `dispatch_tool`

Localiza el bloque `if/elif` que normaliza el nombre de compañía (líneas alrededor de 220-225).
Agrega un `elif` por cada compañía nueva. Ejemplos:
```python
elif "mapfre" in compania_input:
    compania_key = "mapfre"
```

### 3c. Diccionario de nombres de display

Localiza los dicts `compania_nombre` y `compania_display` en `dispatch_tool`.
Agrega la clave nueva con su nombre de display en español. Ejemplo:
```python
"mapfre": "Mapfre Seguros",
```

---

## PASO 4 — Actualizar `config/prompts.yaml`

Lee `config/prompts.yaml`. Localiza la sección `## Formularios disponibles y cuándo entregarlos`.

Para cada compañía NUEVA (no presente aún en el YAML):
1. Agrega un bloque con el encabezado `### NombreCompañía (\`compania: "clave"\`)`.
2. Por cada tipo de formulario disponible, agrega:
   - Nombre del tipo en negrita y su descripción de uso.
   - Triggers: frases que el cliente podría decir para solicitar ese formulario.
3. Si la compañía no tiene `procedimiento_medico`, no lo menciones.
4. Si la compañía tiene `aviso_accidente`, indica que es trámite administrativo (NO escalación).

Ejemplo para Mapfre con solo `reembolso`:
```yaml
  ### Mapfre Seguros (`compania: "mapfre"`)

  **`reembolso`** — Cliente YA pagó y quiere reembolso.
  - Triggers: "ya fui al médico", "ya me atendieron", "pagué de mi bolsillo".

  ---
```

Actualiza también la pregunta de ambigüedad al final de la sección para incluir la nueva compañía.
Por ejemplo: `"¿Con cuál aseguradora tiene su póliza de gastos médicos, AXA, Seguros Monterrey o Mapfre?"`

Mantén las reglas existentes de AXA y Seguros Monterrey sin cambios.

---

## PASO 5 — Resumen final

Al terminar, imprime una tabla con los cambios realizados:

```
setup-forms completado ✓

Compañías configuradas:
  ✓ axa           → reembolso, procedimiento_medico, informe_medico
  ✓ seguros_monterrey → reembolso, informe_medico, aviso_accidente
  [+ nuevas si aplica]

Archivos actualizados:
  ✓ agent/main.py        (FORM_URLS)
  ✓ agent/tools.py       (enum compania + normalización + display names)
  ✓ config/prompts.yaml  (reglas de entrega de formularios)

Para aplicar los cambios reinicia el servidor:
  uvicorn agent.main:app --reload --port 8000
```

---

## REGLAS GENERALES

- Si un directorio de compañía está vacío (sin PDFs), omítelo silenciosamente — no lo agregues a los archivos.
- Si una compañía YA está configurada en los tres archivos, no la modifiques.
- Si un archivo PDF no coincide con ningún tipo conocido, muestra advertencia y pide al desarrollador renombrarlo siguiendo las convenciones anteriores.
- Preserva toda la lógica existente en los tres archivos; solo añade o actualiza las partes relacionadas con formularios.
- NO hardcodees URLs absolutas; usa siempre `_PUBLIC_URL` como prefijo en main.py.
- Habla en español en todos los mensajes al desarrollador.

# Skill: setup-forms
# Sincroniza los formularios PDF disponibles en forms/ con main.py, tools.py y forms.yaml.
# Ejecutar después de agregar o cambiar PDFs de aseguradoras.

Eres el asistente de configuración de formularios para el agente de WhatsApp (AgentKit).
Tu tarea es sincronizar automáticamente los PDFs disponibles en `forms/` con los archivos
que los referencian: `agent/main.py`, `agent/tools.py` y `config/forms.yaml`.

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
  - contiene `programacion` o `procedimiento` → `procedimiento_medico`
  - contiene `informe` → `informe_medico`
  - contiene `accidente` o `aviso` → `aviso_accidente`
  - contiene `consentimiento` → `consentimiento_informado`
  - contiene `veracidad` o `declaracion` → `declaracion_veracidad`
  - contiene `kyc` → `kyc_siniestro`
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

Lee `agent/tools.py` y realiza estos cambios si es necesario:

### 3a. Enum `compania` en la definición de la herramienta `obtener_formularios`

Localiza el campo `"compania"` dentro de `TOOLS` → `obtener_formularios` → `input_schema`.
Actualiza `"enum"` para incluir las claves de todas las compañías descubiertas.

### 3b. Helpers de normalización

Localiza la función `_normalizar_compania`. Agrega un `elif` por cada compañía nueva que no esté
ya contemplada.

---

## PASO 4 — Actualizar `config/forms.yaml`

Lee `config/forms.yaml`. Realiza estos cambios:

### 4a. Sección `companias`
Para cada compañía nueva, agrega una entrada con `nombre_display` y `aliases`.

### 4b. Sección `formularios`
Para cada tipo de formulario nuevo descubierto, agrega una entrada con su `nombre` de display.

### 4c. Sección `escenarios`
Para cada compañía nueva, agrega su clave en `formularios_por_compania` dentro de los escenarios
existentes. Usa estas reglas:
- `reembolso`: si la compañía tiene formulario `reembolso` → `["reembolso"]`
- `reembolso_con_declaracion`: si tiene `declaracion_veracidad` → `["reembolso", "declaracion_veracidad"]`, si no → `["reembolso"]`
- `cirugia`: si tiene `procedimiento_medico` → incluirlo; si tiene `informe_medico` → incluirlo; si tiene `consentimiento_informado` → incluirlo
- `informe_medico`: si tiene `informe_medico` → `["informe_medico"]`
- `accidente`: si tiene `aviso_accidente` → `["aviso_accidente"]`, si no → `null`
- `accidente_con_kyc`: si tiene `kyc_siniestro` → incluir `aviso_accidente` + `kyc_siniestro`, si no → mismo que `accidente`

Si no está seguro de cómo asignar un formulario nuevo a escenarios, pregunta al desarrollador.

---

## PASO 5 — Resumen final

Al terminar, imprime una tabla con los cambios realizados:

```
setup-forms completado ✓

Compañías configuradas:
  ✓ axa           → reembolso, procedimiento_medico, informe_medico
  ✓ seguros_monterrey → reembolso, informe_medico, aviso_accidente, consentimiento_informado, declaracion_veracidad
  ✓ mapfre        → reembolso, procedimiento_medico, informe_medico, aviso_accidente, kyc_siniestro
  [+ nuevas si aplica]

Archivos actualizados:
  ✓ agent/main.py        (FORM_URLS)
  ✓ agent/tools.py       (enum compania + normalización)
  ✓ config/forms.yaml    (catálogo de formularios y escenarios)

Para aplicar los cambios reinicia el servidor:
  uvicorn agent.main:app --reload --port 8000
```

---

## REGLAS GENERALES

- Si un directorio de compañía está vacío (sin PDFs), omítelo silenciosamente — no lo agregues a los archivos.
- Si una compañía YA está configurada en los archivos, actualiza solo lo que cambió (nuevos formularios).
- Si un archivo PDF no coincide con ningún tipo conocido, muestra advertencia y pide al desarrollador renombrarlo.
- Preserva toda la lógica existente en los archivos; solo añade o actualiza las partes relacionadas con formularios.
- NO hardcodees URLs absolutas; usa siempre `_PUBLIC_URL` como prefijo en main.py.
- NO modifiques `config/prompts.yaml` — las reglas de formularios ahora están en `config/forms.yaml`.
- Habla en español en todos los mensajes al desarrollador.

# Handoff — Migración a Meta WhatsApp Cloud API

> Última sesión: **17 de octubre de 2026** (anteriores: 9 y 2 de octubre)
> Rama: `feat/meta-cloud-api` (solo commit local, **sin push ni PR**)
> Worktree: `.claude/worktrees/meta-cloud-api/` dentro del repo
> Runbook de referencia: `guia-whatsapp-api-desde-cero.html` (sin trackear, en la raíz del checkout principal)

---

## 1. Dónde quedamos

El bot **funciona de punta a punta con la API oficial de Meta** usando el **número de prueba** de Meta y el servidor corriendo **localmente** con un túnel de Cloudflare.

| Pieza | Estado |
|---|---|
| Verificación del webhook (GET `hub.challenge`) | ✅ Meta la aceptó |
| Firma HMAC `X-Hub-Signature-256` validada con `META_APP_SECRET` | ✅ |
| App suscrita al campo `messages` | ✅ (se hizo por API) |
| App suscrita a la WABA (`subscribed_apps`) | ✅ (se hizo por API; era la "trampa cara" del runbook) |
| Claude responde + SICAS (búsqueda, verificación por fecha de nacimiento, pólizas, PDF) | ✅ probado desde `+1 737 888 9040` |
| Monitor de sesiones (aviso 2.5 min / cierre 5 min) | ✅ envía bien vía Meta |
| Envío a un número mexicano (`521…` → `52…`) | ⏳ **no probado en real**: `+52 81 8176 4764` no está registrado como destinatario de prueba (error `131030`) |
| Token permanente | ✅ usuario del sistema `backend-whatsapp` (ID `61595206172669`), sin caducidad — verificado 9-oct-2026 |
| Número real del negocio | ❌ pendiente |
| Hosting de producción con Meta | ❌ pendiente (Railway sigue en producción con **Whapi**) |

**Producción no se tocó:** el servicio de Railway sigue en la rama `main` con `WHATSAPP_PROVIDER=whapi`.

---

## 2. Datos de Meta (no son secretos)

| Dato | Valor |
|---|---|
| Portafolio comercial | Gonzalez Loredo Asesoria Patrimonial (**sin verificar**) |
| App | Gonzalez Loredo WA Bot — App ID `28837436845844340` |
| WABA ID | `1586670603131302` |
| Número de prueba | `+1 555 200 1391` |
| Phone Number ID (prueba) | `1264214943440306` |
| Destinatario de prueba registrado | `+1 737 888 9040` |
| Versión de Graph API usada | `v21.0` (configurable con `META_API_VERSION`) |

Los secretos (`META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `ANTHROPIC_API_KEY`, SICAS) viven **solo** en `.claude/worktrees/meta-cloud-api/.env`, que git ignora.

> ⚠️ En Meta, la **Callback URL** sigue apuntando a un túnel temporal que ya no existe
> (`https://suggestion-own-joint-tommy.trycloudflare.com/webhook`, 9-oct). Hay que actualizarla
> cada vez que se levante un túnel nuevo, o al desplegar en el hosting definitivo (ver §4).

---

## 3. Qué cambió en el código (commit de esta sesión)

- **`agent/providers/meta.py` (nuevo):** adaptador de Meta Cloud API.
  - Verificación GET del webhook; responde 403 si el token no coincide.
  - Validación de la firma `X-Hub-Signature-256`. Si `META_APP_SECRET` está vacío, solo avisa en el log.
  - Parseo de mensajes `text`, `button` e `interactive`. Ignora los `statuses`.
  - Normaliza los números mexicanos `521XXXXXXXXXX` → `52XXXXXXXXXX` al **enviar**.
  - Parte los mensajes de más de 4096 caracteres.
  - Timeout de 10 s.
- **`agent/providers/base.py`:** nuevo método `webhook_autorizado()`. Whapi sigue usando `WEBHOOK_SECRET` y Meta lo sobreescribe con la firma HMAC.
- **`agent/main.py`:**
  - Usa `proveedor.webhook_autorizado()`.
  - **Dedup por `mensaje_id`**, porque Meta reintenta el webhook si tardamos.
- **`requirements.txt`:** `sqlalchemy` → `sqlalchemy[asyncio]`. SQLAlchemy 2.1 ya no instala `greenlet` y sin él la app **no arranca**. Esto también afecta a un rebuild en Railway de `main`.
- **`.env.example`:** variables de Meta documentadas (`META_APP_SECRET`, `META_API_VERSION`).

---

## 4. Cómo retomar el entorno local

Herramientas instaladas en esta Mac: `~/.local/bin/uv`, `~/.local/bin/cloudflared` y `.venv/` con Python 3.11 dentro del worktree. Python del sistema = 3.9, **no sirve**.

```bash
cd ~/Documents/src/whatsapp-agentkit/.claude/worktrees/meta-cloud-api

# Terminal 1 — servidor
.venv/bin/uvicorn agent.main:app --port 8000

# Terminal 2 — túnel público (la URL cambia cada vez)
~/.local/bin/cloudflared tunnel --no-autoupdate --url http://localhost:8000
```

Actualizar la Callback URL en Meta por API (sin buscar la pantalla), con la URL nueva del túnel:

```bash
set -a; . ./.env; set +a
NUEVA_URL="https://<nuevo-subdominio>.trycloudflare.com/webhook"
curl -s -X POST "https://graph.facebook.com/v21.0/28837436845844340/subscriptions" \
  --data-urlencode "object=whatsapp_business_account" \
  --data-urlencode "callback_url=$NUEVA_URL" \
  --data-urlencode "verify_token=$META_VERIFY_TOKEN" \
  --data-urlencode "fields=messages" \
  --data-urlencode "access_token=28837436845844340|$META_APP_SECRET"
```

Comprobaciones útiles:

```bash
# ¿Qué token tengo y cuándo caduca?
curl -s -G https://graph.facebook.com/v21.0/debug_token \
  --data-urlencode "input_token=$META_ACCESS_TOKEN" --data-urlencode "access_token=$META_ACCESS_TOKEN"

# ¿Mi app sigue suscrita a la WABA? (debe aparecer "Gonzalez Loredo WA Bot")
curl -s "https://graph.facebook.com/v21.0/1586670603131302/subscribed_apps?access_token=$META_ACCESS_TOKEN"
```

> 🔒 Con `ENVIRONMENT=development`, el log imprime el system prompt completo y los datos de los clientes
> (nombres, fechas de nacimiento, pólizas). No compartas ni guardes esos logs. En producción usa `ENVIRONMENT=production`.

---

## 5. Pendientes, en orden

### 5.1 Token permanente (Fase 6 del runbook) — ✅ hecho el 9-oct (punto 7 el 17-oct)

> Resultado: token de usuario del sistema `backend-whatsapp`, `expires_at: 0`, probado de punta a punta (envíos a Meta con `200 OK`).

1. `business.facebook.com` → ⚙️ Configuración del negocio → **Usuarios → Usuarios del sistema** → **Agregar**.
   - Nombre: `backend-whatsapp`.
   - Rol: **Empleado**.
2. **Asignar activos**:
   - la app *Gonzalez Loredo WA Bot*, con control total,
   - la cuenta de WhatsApp (WABA `1586670603131302`), con control total.
3. **Generar nuevo token**:
   - app: *Gonzalez Loredo WA Bot*,
   - permisos `whatsapp_business_messaging` y `whatsapp_business_management`,
   - caducidad **Nunca**.
4. Cópialo **de inmediato** (solo se muestra una vez) y pégalo en `META_ACCESS_TOKEN` del `.env`.
5. Verifica con `debug_token` (§4) que `expires_at` sea `0`, es decir, sin caducidad. Si quedó en 60 días, regenera.
6. Si el token aparece en una captura, chat o log, **rótalo**.
7. ✅ **Hecho el 17-oct:** https://t-protg.com/ quedó como URL de política de privacidad (verificado por API con `fields=privacy_policy_url`). Se hizo **a mano** en developers.facebook.com → app → *Configuración de la app → Básica*. Por API falla con el error `(#10) Changing app settings through API calls has been disabled`, y conviene dejar ese bloqueo activo.

### 5.2 Terminar la prueba del número mexicano (opcional pero recomendado)

> ⏳ **Pendiente (17-oct):** no controlamos ese número. Hay que **agendar una videollamada con la dueña
> del número** para hacer juntos los pasos 1–3: ella recibe el código de verificación y envía el "Hola".
> Antes de la llamada: levantar el servidor y el túnel (§4) y actualizar la Callback URL.
> El número ya está en `NUMEROS_AUTORIZADOS` en sus dos formatos (`528181764764` y `5218181764764`).

1. Meta → *Paso 1. Pruébalo* → **Destinatario** → agregar **+52 81 8176 4764**. País México y 10 dígitos, **sin el "1"**.
2. Confirmar el código que llega por WhatsApp a ese teléfono.
3. Desde ese teléfono escribir "Hola" al `+1 555 200 1391` y confirmar que la respuesta llega. Valida la conversión `521` → `52` en real.

### 5.3 Número real del negocio (Fase 5 / "Paso 2: Configuración de producción")

> ✅ **Decisión (17-oct):** usar un **chip prepago nuevo, solo para el bot**. El número de Whapi es de una
> asistente que lo sigue usando para hablar con los clientes, así que no se migra.
> ⏳ Siguiente paso: comprar el chip (de preferencia lada 81), activarlo y registrarlo con la CURP.
> **No instalarle WhatsApp.**

- **Decidir qué número conectar.** Un número conectado a la Cloud API **deja de funcionar en la app de WhatsApp del celular**. Si es el número que hoy usa Whapi, el cambio es definitivo, así que hay que planear el corte. Alternativa del runbook: un chip prepago dedicado, al que hay que recargar cada ~2 meses y nunca instalarle WhatsApp.
- En Meta: *Paso 2* → **Agregar número** → código por SMS o llamada → esperar a que se apruebe el **nombre visible**.
- Copia el **nuevo Phone Number ID** (será distinto al de prueba) y ponlo en `META_PHONE_NUMBER_ID`. La WABA no cambia.
- Si el número queda en estado "Pendiente", puede requerir registro por API con un PIN de 6 dígitos (`POST /<PHONE_ID>/register`).

### 5.4 Pasar la app a modo **Activo**

- ✅ La **URL de política de privacidad** ya está configurada (`https://t-protg.com/`, 17-oct). Ya no hace falta la ruta `/privacidad`.
- Falta cambiar el interruptor de la app de *Desarrollo* a **Activo**.

### 5.5 Abrir el bot a clientes reales

- **Lista blanca:** `NUMEROS_AUTORIZADOS` en `agent/main.py` hoy limita a quién contesta el bot. Para clientes reales hay que quitarla o ampliarla.
- `SELF_CHAT_NUMEROS` (`17378889040`) no aplica con Meta, porque la Cloud API no envía mensajes propios. Se puede limpiar.

### 5.6 Notificación al asesor (`AGENT_WHATSAPP_NUMBER`) — requiere plantilla

- Ese aviso lo inicia el negocio. Si el asesor no le escribió al número en las últimas 24 h, Meta lo acepta (200) **pero no lo entrega**.
- Solución: crear una **plantilla de utilidad** en WhatsApp Manager (requiere método de pago, ≈ US$0.01 por mensaje) y enviar la notificación como `type: "template"`. Esto requiere un cambio de código en `agent/providers/meta.py` y `agent/main.py`.

### 5.7 Hosting de producción

Meta no hospeda el código: el bot necesita un servidor con HTTPS. Comparativo de la sesión:

| Opción | Costo/mes | Nota |
|---|---|---|
| Railway Hobby (actual) | $5 | Funciona tal cual |
| Fly.io shared-cpu-1x 256 MB | ~$2 | Siempre encendido; requiere `fly.toml` |
| Render Free | $0 | Se duerme tras 15 min; el primer mensaje tarda ~1 min |
| Koyeb Free | $0 | Se duerme tras 1 h |
| Cloud Run (request-based) | ~$0 | ❌ los avisos de 2.5 y 5 min no se disparan con el CPU congelado |
| Oracle Always Free | $0 | Tú administras la VM; Oracle recupera VMs inactivas |

Al desplegar, configura en el hosting:
- `WHATSAPP_PROVIDER=meta`, `META_ACCESS_TOKEN` (el permanente), `META_PHONE_NUMBER_ID` (del número real), `META_VERIFY_TOKEN`, `META_APP_SECRET`,
- las variables de Anthropic, SICAS y `AGENT_WHATSAPP_NUMBER`,
- `PUBLIC_URL` (para los PDFs de `/forms`) y `ENVIRONMENT=production`.

Después actualiza la Callback URL (§4) a `https://<dominio>/webhook`.

### 5.8 Mejoras menores detectadas

- `main.py` registra `Respuesta a …` en el log aunque el envío haya fallado. Conviene usar el `bool` que devuelve `enviar_mensaje`.
- Los dedups (`_ids_procesados`, eco) y el estado de las conversaciones viven en memoria: se pierden al reiniciar o si el hosting se duerme.

### 5.9 Cerrar la rama

- `git push -u origin feat/meta-cloud-api` y abrir el PR cuando 5.1–5.7 estén listos.
- Cuando ya no se use, borra el worktree con `git worktree remove .claude/worktrees/meta-cloud-api`.

---

## 6. Limitaciones aceptadas (portafolio sin verificar)

- **250 conversaciones/día iniciadas por el negocio.** Las respuestas a clientes que escriben primero **no tienen límite**.
- Fuera de la ventana de 24 h solo se pueden enviar **plantillas aprobadas**.
- Para subir el límite: completar *Información del negocio* en el portafolio y luego *Centro de seguridad → Iniciar verificación*.

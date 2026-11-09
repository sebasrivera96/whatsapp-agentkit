# Handoff — Migración a Meta WhatsApp Cloud API

> Última sesión: **9 de noviembre de 2026** (anteriores: 18, 17, 9 y 2 de octubre)
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
| Ambiente de pruebas en Azure (§4.1) | 🟡 desplegado y verificado; falta apuntar Meta y probar |
| Hosting de producción con Meta | ❌ pendiente (Whapi se abandonó el 4-nov; ver §4.2) |
| Claves en `.env` local y Azure | ❌ **obsoletas**: la clave de Anthropic da 401 desde la rotación (ver §4.2) |

> **▶ Para retomar (sesión del 9-nov):** **primero** pon las claves nuevas de Anthropic y SICAS en el `.env`
> local y en Azure (§4.2, pasos 1–3). Sin eso el bot no contesta en ningún ambiente.
> Después sigue los pendientes de §4.1: apuntar la Callback URL a Azure y probar con un WhatsApp real.

**Ya no hay producción con Whapi:** el servicio de Railway está caído desde ~14-oct y el canal de Whapi se borró el 9-nov (ver §4.2).

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

### 4.1 Ambiente de pruebas en Azure (creado el 18-oct)

Sustituye al túnel: URL fija con HTTPS y siempre encendido. **Solo para pruebas.** El crédito es de la suscripción
*Visual Studio Enterprise* (US$150/mes, solo dev/test), así que producción **no** va aquí.

| Dato | Valor |
|---|---|
| Suscripción | Visual Studio Enterprise Subscription (`a7562d20-b172-4095-b1aa-d2e032909b39`), directorio personal |
| Grupo de recursos | `rg-whatsapp-bot-test` (South Central US) |
| Container App | `wa-bot-test`, réplicas mín = máx = 1 (siempre encendida; el estado vive en memoria) |
| URL | `https://wa-bot-test.nicefield-03aa0d61.southcentralus.azurecontainerapps.io` |
| Webhook | `…/webhook`, verificación `hub.challenge` probada con curl ✅ |
| Secretos | `anthropic-api-key`, `meta-access-token`, `meta-verify-token`, `meta-app-secret`, `sicas-username`, `sicas-password` |
| Variables normales | `WHATSAPP_PROVIDER=meta`, `META_PHONE_NUMBER_ID`, `SICAS_API_URL`, `AGENT_WHATSAPP_NUMBER`, `PUBLIC_URL` (= la URL de arriba), `PORT=8000`, `DATABASE_URL` (SQLite local del contenedor) |
| Costo estimado | ~US$10–20/mes del crédito |

Azure CLI se instaló con `~/.local/bin/uv tool install --python 3.12 --with pip azure-cli` (sin Homebrew; el `--with pip`
es necesario para las extensiones). La sesión de `az login` queda guardada en `~/.azure`.

**Pendientes, en orden:**

1. ✅ **`ENVIRONMENT=production`** — aplicado por el usuario el 18-oct (revisión `wa-bot-test--0000003`). Los logs ya no imprimen datos de clientes.
2. **Apuntar Meta a Azure:** en developers.facebook.com → WhatsApp → Configuration, usa la Callback URL
   `https://wa-bot-test.nicefield-03aa0d61.southcentralus.azurecontainerapps.io/webhook` con el mismo `META_VERIFY_TOKEN`.
   También se puede hacer por API con el `curl` de arriba, cambiando `NUEVA_URL`. Meta admite **una sola** Callback URL:
   mientras apunte a Azure, el túnel local no recibe nada.
3. **Probar con un WhatsApp real** al número de prueba y revisar los logs. Pon atención a SICAS: no se sabe si exige
   IPs autorizadas. Si falla desde Azure pero funciona en local, ojo: el plan Consumption sale por **~190 IPs
   compartidas** de la región (`--query properties.outboundIpAddresses`), así que no es práctico pedirle a SICAS que
   las autorice todas. En ese caso habría que darle a la app una IP fija (ambiente con VNet + NAT Gateway,
   ~US$35/mes extra del crédito) o probar SICAS solo en local.
4. Probar también el monitor de sesiones (aviso a los 2.5 min y cierre a los 5 min).

**Operación:**

```bash
# Redesplegar después de cambiar código (construye en la nube, no requiere Docker)
az containerapp up -n wa-bot-test -g rg-whatsapp-bot-test --source .

# Cambiar una variable o un secreto
az containerapp update -n wa-bot-test -g rg-whatsapp-bot-test --set-env-vars CLAVE=valor
az containerapp secret set -n wa-bot-test -g rg-whatsapp-bot-test --secrets meta-access-token=<valor>

# Ver logs en vivo
az containerapp logs show -n wa-bot-test -g rg-whatsapp-bot-test --follow --format text

# Borrar TODO el ambiente (app, registro de imágenes, logs)
az group delete -n rg-whatsapp-bot-test
```

### 4.2 Brecha de Railway (oct-2026) y rotación de claves

El 21-oct Railway reveló un incidente: es posible que se hayan descifrado variables de entorno de algunos clientes, y los atacantes
buscaban claves de IA. El 23-oct Railway avisó que este workspace coincidía con lo que buscaban (correo auténtico:
SPF/DKIM/DMARC pasan). Todo secreto guardado en Railway antes de esa fecha se considera filtrado.

| Secreto | Estado |
|---|---|
| `ANTHROPIC_API_KEY` | ✅ rotada (la vieja da 401) |
| `SICAS_USERNAME` / `SICAS_PASSWORD` | ✅ rotados |
| `WHAPI_TOKEN` | ✅ canal de Whapi borrado (9-nov); variable borrada de Railway |
| `WEBHOOK_SECRET` | ✅ variable borrada de Railway (ver §5.7: hay que crear una nueva para que arranque) |
| `.env` local de este worktree | ❌ **sigue con los valores viejos** |
| Secretos de Azure `wa-bot-test` | ❌ **siguen con los valores viejos** (mismos que el `.env` local) |

**Arreglo del entorno local y de Azure, en orden:**

1. **`.env` local:** en `.claude/worktrees/meta-cloud-api/.env`, reemplaza `ANTHROPIC_API_KEY`, `SICAS_USERNAME` y
   `SICAS_PASSWORD` con los valores nuevos. No los pegues en un chat ni en este archivo.
2. **Azure:** sube los mismos valores desde el `.env`, así no aparecen en la terminal ni en el historial, y reinicia
   la revisión para que los tome (los secretos no se recargan solos):
   ```bash
   cd .claude/worktrees/meta-cloud-api
   set -a && . ./.env && set +a
   az containerapp secret set -n wa-bot-test -g rg-whatsapp-bot-test \
     --secrets anthropic-api-key="$ANTHROPIC_API_KEY" sicas-username="$SICAS_USERNAME" sicas-password="$SICAS_PASSWORD"
   az containerapp revision restart -n wa-bot-test -g rg-whatsapp-bot-test \
     --revision $(az containerapp show -n wa-bot-test -g rg-whatsapp-bot-test --query properties.latestRevisionName -o tsv)
   ```
   (`az` está en `~/.local/bin/az` si no está en el `PATH`.)
3. **Verificar** sin imprimir las claves. Las dos deben dar `200`, y la comparación de SICAS debe decir `igual`:
   ```bash
   set -a && . ./.env && set +a
   curl -s -o /dev/null -w 'local: %{http_code}\n' https://api.anthropic.com/v1/models \
     -H "x-api-key: $ANTHROPIC_API_KEY" -H 'anthropic-version: 2023-06-01'
   AZ_KEY=$(az containerapp secret show -n wa-bot-test -g rg-whatsapp-bot-test --secret-name anthropic-api-key --query value -o tsv)
   curl -s -o /dev/null -w 'azure: %{http_code}\n' https://api.anthropic.com/v1/models \
     -H "x-api-key: $AZ_KEY" -H 'anthropic-version: 2023-06-01'
   [ "$(az containerapp secret show -n wa-bot-test -g rg-whatsapp-bot-test --secret-name sicas-password --query value -o tsv)" = "$SICAS_PASSWORD" ] \
     && echo 'sicas: igual' || echo 'sicas: distinto'
   ```
4. **Probar de punta a punta:** levanta el servidor local (§4) y escribe al número de prueba para confirmar que Claude
   contesta y que SICAS encuentra pólizas. Después repite contra Azure (§4.1).

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
| AWS Lightsail 512 MB con IPv4 | $5 | Tú administras la VM y el HTTPS; no ahorra nada |
| AWS EC2 t4g.nano + IPv4 pública | ~$6–7 | AWS cobra la IPv4 aparte (~$3.65); más caro que Railway |
| Azure VM B1ls + IP pública | ~$6–7 | Igual que EC2: VM que administras tú |
| Azure App Service F1 (gratis) | $0 | ❌ sin *Always On* ni cuota de CPU suficiente; mismo problema que Cloud Run |

Precios aproximados (oct-2026, revisar antes de decidir). Requisitos del bot: siempre encendido (avisos de 2.5 y 5 min), HTTPS público y Docker. Conclusión (18-oct): AWS/Azure no salen más baratos que Railway para un solo contenedor pequeño. El único ahorro real es Fly.io (~$3/mes) u Oracle gratis, y solo vale la pena aprovechar el corte a Meta (que ya implica redeploy) para moverse.

Al desplegar, configura en el hosting:
- `WHATSAPP_PROVIDER=meta`, `META_ACCESS_TOKEN` (el permanente), `META_PHONE_NUMBER_ID` (del número real), `META_VERIFY_TOKEN`, `META_APP_SECRET`,
- las variables de Anthropic, SICAS y `AGENT_WHATSAPP_NUMBER`,
- `PUBLIC_URL` (para los PDFs de `/forms`) y `ENVIRONMENT=production`.

Después actualiza la Callback URL (§4) a `https://<dominio>/webhook`.

**Estado de Railway (9-nov):** el servicio `whatsapp-agentkit` (proyecto `celebrated-serenity`) se cayó ~14-oct con
`ModuleNotFoundError: No module named 'greenlet'`: un rebuild de `main` instaló SQLAlchemy 2.1, que ya no trae `greenlet`.
✅ **Arreglado el 9-nov:** `sqlalchemy[asyncio]` quedó en `main` (commit `44e1cee`, hecho desde la web de GitHub porque
esta Mac no tiene credenciales de GitHub), y se creó un `WEBHOOK_SECRET` nuevo en Railway. Se mantiene Railway como
candidato a producción. Si se usa Railway para Meta:

- **`WEBHOOK_SECRET` y `9f6986e`:** `main` tiene el commit `9f6986e`, que hace que la app **no arranque** con
  `ENVIRONMENT=production` sin `WEBHOOK_SECRET`. Por eso se creó uno nuevo en Railway; no lo borres mientras corra `main`.
- **Conflicto al fusionar esta rama:** esta rama no tiene `9f6986e` y movió la validación a `proveedor.webhook_autorizado()`.
  Al fusionar con `main` habrá conflicto en `agent/main.py`. Adapta el arranque seguro a cada proveedor: con Meta exige
  `META_APP_SECRET` (hoy `meta.py` solo avisa en el log si falta); con Whapi, `WEBHOOK_SECRET`.
- Antes de guardar `META_ACCESS_TOKEN` y `META_APP_SECRET` en Railway, recuerda la brecha (§4.2).

### 5.8 Mejoras menores detectadas

- `main.py` registra `Respuesta a …` en el log aunque el envío haya fallado. Conviene usar el `bool` que devuelve `enviar_mensaje`.
- Los dedups (`_ids_procesados`, eco) y el estado de las conversaciones viven en memoria: se pierden al reiniciar o si el hosting se duerme.

### 5.9 Idea para después del corte: que el asesor conteste desde el número del bot

Con Meta, el número del bot no se puede usar en la app de WhatsApp. Hoy el asesor atiende desde su propio número tras la escalación, y eso basta. Un conocido usa un panel propio (PWA) para responder a mano desde el número del bot; **se decidió no hacerlo por ahora** (18-oct).

Retomar solo si aparece alguno de estos problemas:
- clientes confundidos porque el asesor les escribe desde otro número;
- la plantilla de §5.6 complica el aviso al asesor (un panel con push notifications lo evitaría).

Opciones, de menor a mayor esfuerzo:
1. **Comando de reenvío:** el asesor le escribe al bot `/r 5218… texto` y el bot lo reenvía al cliente. Sin interfaz nueva.
2. **Inbox existente** como Chatwoot (open source, compatible con Cloud API).
3. **Coexistencia de Meta** (mismo número en la app WhatsApp Business y en la API): confirmar si está disponible en México y sin verificación del negocio.
4. PWA propia: login, tiempo real, push y protección de datos de pólizas. Es un proyecto aparte.

### 5.10 Cerrar la rama

- `git push -u origin feat/meta-cloud-api` y abrir el PR cuando 5.1–5.7 estén listos.
- Cuando ya no se use, borra el worktree con `git worktree remove .claude/worktrees/meta-cloud-api`.

---

## 6. Limitaciones aceptadas (portafolio sin verificar)

- **250 conversaciones/día iniciadas por el negocio.** Las respuestas a clientes que escriben primero **no tienen límite**.
- Fuera de la ventana de 24 h solo se pueden enviar **plantillas aprobadas**.
- Para subir el límite: completar *Información del negocio* en el portafolio y luego *Centro de seguridad → Iniciar verificación*.

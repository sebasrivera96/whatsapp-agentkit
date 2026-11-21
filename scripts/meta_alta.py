"""Alta del número real en Meta Cloud API, un paso a la vez.

Lee el token con python-dotenv (nunca con el shell) y no lo imprime.
Uso:
  python scripts/meta_alta.py check                       # GET: token + números de la cuenta de mensajes
  python scripts/meta_alta.py add                         # POST phone_numbers
  python scripts/meta_alta.py request <PHONE_ID> SMS|VOICE
  python scripts/meta_alta.py verify <PHONE_ID> <CODIGO>
  python scripts/meta_alta.py register <PHONE_ID>         # usa META_REGISTRATION_PIN del .env
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path

from dotenv import dotenv_values

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
TOKEN = ENV.get("META_ACCESS_TOKEN") or sys.exit("Falta META_ACCESS_TOKEN en .env")
VERSION = ENV.get("META_API_VERSION") or "v21.0"
BASE = f"https://graph.facebook.com/{VERSION}"
CUENTA_MENSAJES = "1702606288130438"


def llamar(metodo, ruta, datos=None):
    url = f"{BASE}/{ruta}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = None
    if datos is not None:
        body = urllib.parse.urlencode(datos).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            estado, texto = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        estado, texto = e.code, e.read().decode()
    print(f"{metodo} /{ruta.split('?')[0]} -> {estado}")  # sin query: nunca imprimir el token
    texto = texto.replace(TOKEN, "<TOKEN>")
    try:
        print(json.dumps(json.loads(texto), indent=2, ensure_ascii=False))
    except ValueError:
        print(texto)


paso = sys.argv[1] if len(sys.argv) > 1 else ""
if paso == "check":
    llamar("GET", "debug_token?" + urllib.parse.urlencode({"input_token": TOKEN}))
    llamar("GET", f"{CUENTA_MENSAJES}/phone_numbers?fields=id,display_phone_number,verified_name,status,code_verification_status,name_status")
elif paso == "add":
    llamar("POST", f"{CUENTA_MENSAJES}/phone_numbers",
           {"cc": "52", "phone_number": "8123785486",
            "verified_name": "Gonzalez Loredo Asesoria Patrimonial"})
elif paso == "request":
    llamar("POST", f"{sys.argv[2]}/request_code", {"code_method": sys.argv[3], "language": "es"})
elif paso == "verify":
    llamar("POST", f"{sys.argv[2]}/verify_code", {"code": sys.argv[3]})
elif paso == "register":
    pin = ENV.get("META_REGISTRATION_PIN") or sys.exit("Falta META_REGISTRATION_PIN en .env")
    llamar("POST", f"{sys.argv[2]}/register", {"messaging_product": "whatsapp", "pin": pin})
else:
    sys.exit(__doc__)

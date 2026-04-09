# agent/sicas_client.py — Cliente asíncrono para el CRM SICAS Online
# Portado de SICAS_AI/sicas_client.py (requests → httpx.AsyncClient)

"""
Envuelve la API REST de SICAS Online con refresh automático de token JWT.
Los tokens expiran en 3 minutos; este cliente los renueva cada 2m30s.
"""

import time
import asyncio
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("agentkit")


@dataclass
class SICASClient:
    base_url: str
    username: str
    password: str
    debug: bool = False
    _token: str | None = field(default=None, repr=False)
    _token_fetched_at: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def get_fresh_token(self) -> str:
        """Retorna un token válido, refrescando si han pasado más de 2m30s."""
        async with self._lock:
            if time.time() - self._token_fetched_at > 150:
                token = await self._fetch_token()
                if not token:
                    raise RuntimeError("No se pudo autenticar con SICAS API. Verifica las credenciales.")
                self._token = token
                self._token_fetched_at = time.time()
                logger.debug("Token SICAS renovado")
        return self._token

    async def _fetch_token(self) -> str | None:
        """Obtiene un nuevo token de autenticación desde SICAS."""
        url = f"{self.base_url}/Security/GetToken"
        params = {"sUserName": self.username, "sPassword": self.password}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, params=params)
                response.raise_for_status()
                data = response.json()
                if data.get("Sucess"):
                    return data["Token"]
                logger.error("SICAS auth falló: %s", data)
                return None
        except httpx.HTTPError as e:
            logger.error("Error HTTP al obtener token SICAS: %s", e)
            return None

    async def search_customers(self, name: str) -> list[dict]:
        """
        Busca clientes por nombre/apellido usando coincidencia palabra por palabra.
        Retorna lista deduplicada con IDCli, NombreCompleto y RFC.
        """
        token = await self.get_fresh_token()
        url = f"{self.base_url}/Report/ReadData"
        words = [w.upper() for w in name.split() if w]

        async def _post(keycode: str, body: dict, label: str):
            if self.debug:
                logger.debug("[SICAS] %s", label)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": token, "Prop_KeyCode": keycode},
                    data=body,
                )
                resp.raise_for_status()
                data = resp.json()
                resp_obj = data.get("Response", [{}])[0]
                table_wrapper = next(iter(resp_obj.values()), {}) if resp_obj else {}
                rows = table_wrapper.get("Data", [])
                return data, rows

        seen_ids: set[int] = set()
        results: list[dict] = []

        for word in words:
            for keycode, cond_key, field_name in [
                ("HWS_CLI", "Conditions",       "CatContactos.ApellidoP"),
                ("HWS_CLI", "ConditionsDirect", "ApellidoP"),
            ]:
                body = {
                    "PageRequested": 1,
                    "ItemsForPage": 50,
                    "SortFields": "NombreCompleto",
                    "FormatResponse": 2,
                    cond_key: f"Apellido;0;1;{word};;0;0;{field_name}",
                }
                try:
                    data, rows = await _post(keycode, body, f"{keycode} ApellidoP LIKE '{word}'")
                    if data.get("Sucess") and rows:
                        for row in rows:
                            rid = row.get("IDCli")
                            if rid not in seen_ids:
                                seen_ids.add(rid)
                                results.append(row)
                        break
                except httpx.HTTPError as e:
                    logger.warning("Error HTTP en search_customers (%s): %s", keycode, e)

        return results

    async def get_policies(self, id_cli: int) -> list[dict]:
        """Retorna todas las pólizas/documentos de un cliente dado su IDCli."""
        token = await self.get_fresh_token()
        url = f"{self.base_url}/Report/ReadData"
        headers = {"Authorization": token, "Prop_KeyCode": "HWS_DOCTOS"}
        body = {
            "PageRequested": 1,
            "ItemsForPage": 100,
            "SortFields": "FDesde",
            "FormatResponse": 2,
            "ConditionsDirect": f"Cliente;0;0;{id_cli};;0;0;IDCli",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, headers=headers, data=body)
                response.raise_for_status()
                data = response.json()
                if data.get("Sucess"):
                    resp_obj = data.get("Response", [{}])[0]
                    table_wrapper = next(iter(resp_obj.values()), {}) if resp_obj else {}
                    return table_wrapper.get("Data", [])
        except httpx.HTTPError as e:
            logger.error("Error HTTP en get_policies (IDCli=%s): %s", id_cli, e)
        return []

    async def get_policy_document_link(self, id_docto: int) -> list[dict]:
        """
        Obtiene los archivos digitales asociados a una póliza.
        Cada registro tiene PathWWW (URL de descarga), FileName, Ext y SizeFile.
        """
        token = await self.get_fresh_token()
        url = f"{self.base_url}/DigitalCenter/GetFilesAdv"
        headers = {"Authorization": token}
        body = {
            "Identity": "H02",   # H02 = Póliza
            "ValuePK": id_docto,
            "URLSecurity": 0,    # 0 = URL directa sin seguridad adicional
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, headers=headers, data=body)
                response.raise_for_status()
                data = response.json()
                if data.get("Sucess"):
                    return data.get("ListData", [])
        except httpx.HTTPError as e:
            logger.error("Error HTTP en get_policy_document_link (IDDocto=%s): %s", id_docto, e)
        return []

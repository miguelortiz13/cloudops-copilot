"""
TfStateService — Que recursos gestiona Terraform, leido de los estados reales.

Hasta aqui la plataforma solo podia *sospechar* que algo se creo fuera de IaC.
La regla de tags constata que nadie declaro el recurso, no que se hiciera a
mano, y la tabla `resourcechanges` —la unica evidencia dura— solo conserva unos
catorce dias. El inventario historico quedaba fuera del alcance de las dos.

Los estados de Terraform cierran esa brecha: **todo id que aparece en un estado
esta gestionado, con certeza, y lo que no aparece en ninguno no lo esta**. Sin
ventana de retencion y sin heuristica.

Lo que este modulo NO hace, a proposito
---------------------------------------
Un archivo de estado contiene los atributos completos de cada recurso, y ahi
viajan secretos: cadenas de conexion, llaves de acceso, contrasenas de
administrador. De cada estado se extraen unicamente el `id` y el `type` de los
recursos gestionados; **el resto se descarta sin registrarse, sin cachearse y
sin salir de este modulo**. Tampoco se escribe nada: el Service Principal tiene
permiso de escritura sobre esa cuenta porque es el mismo que ejecuta los
pipelines de infraestructura, pero la plataforma solo lee.

Limite que hay que declarar siempre
-----------------------------------
Esto es verdad sobre los estados accesibles. Un equipo que guarde su estado en
otra cuenta veria sus recursos como no gestionados, y la interfaz tiene que
poder decir sobre cuantos estados se calculo la cifra, igual que hace con la
cobertura de costos.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set
from xml.etree import ElementTree

import requests

from app.core import config

STORAGE_SCOPE = "https://storage.azure.com/.default"
STORAGE_API_VERSION = "2021-08-06"

ENABLED = os.getenv("TFSTATE_ENABLED", "true").strip().lower() in ("1", "true", "yes") and bool(config.TFSTATE_ACCOUNT)
# Fuentes (cuenta, contenedor). Sin ninguna, la cobertura real de IaC queda
# desactivada.
SOURCES = config.TFSTATE_SOURCES
ACCOUNT = ",".join(cuenta for cuenta, _ in SOURCES)
CONTAINER = ",".join(sorted({contenedor for _, contenedor in SOURCES}))

# Los estados cambian cuando alguien despliega, no cada minuto: seis horas de
# cache evitan releer decenas de megabytes en cada consulta del panel.
TTL_SECONDS = int(os.getenv("TFSTATE_CACHE_TTL_SECONDS", "21600"))

REQUEST_TIMEOUT = float(os.getenv("TFSTATE_REQUEST_TIMEOUT", "30"))
MAX_WORKERS = int(os.getenv("TFSTATE_WORKERS", "6"))

# Prefijos de blob que se ignoran. Vacio por defecto: es preferible contarlo
# todo y que el panel muestre la lista de estados leidos a decidir por el
# equipo que sus pruebas no cuentan.
EXCLUDE_PREFIXES = [
    p.strip() for p in os.getenv("TFSTATE_EXCLUDE_PREFIXES", "").split(",") if p.strip()
]


class TfStateService:
    """Indice de recursos gestionados por Terraform, leido de los estados."""

    def __init__(self, agent):
        self.agent = agent
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------

    def _token(self) -> Optional[str]:
        credenciales = getattr(self.agent, "azure_credentials", None)
        if credenciales is None:
            return None
        try:
            return credenciales.get_token(STORAGE_SCOPE).token
        except Exception as exc:
            print(f"[TfStateService] No se pudo obtener token de storage: {exc}")
            return None

    def _listar_blobs(self, token: str, cuenta: str, contenedor: str) -> List[str]:
        """Nombres de los estados de un contenedor, siguiendo la paginacion."""
        nombres: List[str] = []
        marker = ""
        base = f"https://{cuenta}.blob.core.windows.net/{contenedor}"
        cabeceras = {"Authorization": f"Bearer {token}", "x-ms-version": STORAGE_API_VERSION}

        while True:
            url = f"{base}?restype=container&comp=list"
            if marker:
                url += f"&marker={marker}"
            respuesta = requests.get(url, headers=cabeceras, timeout=REQUEST_TIMEOUT)
            if respuesta.status_code != 200:
                raise RuntimeError(
                    f"El listado de estados de {cuenta}/{contenedor} respondio {respuesta.status_code}"
                )
            raiz = ElementTree.fromstring(respuesta.text)
            for blob in raiz.iter("Blob"):
                nombre = blob.findtext("Name")
                if nombre and nombre.endswith(".tfstate"):
                    nombres.append(nombre)
            marker = (raiz.findtext("NextMarker") or "").strip()
            if not marker:
                break
        return nombres

    @staticmethod
    def _extraer(contenido: bytes) -> Dict[str, Any]:
        """
        Saca del estado solo lo que hace falta: ids y tipos.

        El objeto completo se descarta al salir de esta funcion. Nada de lo que
        contiene —ni un atributo, ni un fragmento en un mensaje de error— debe
        acabar en un log ni en una respuesta del API.
        """
        try:
            estado = json.loads(contenido)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"ids": set(), "tipos": {}, "ok": False}

        ids: Set[str] = set()
        tipos: Dict[str, int] = {}
        for recurso in estado.get("resources", []):
            if recurso.get("mode") != "managed":
                continue
            tipo = str(recurso.get("type") or "")
            for instancia in recurso.get("instances", []):
                atributos = instancia.get("attributes") or {}
                rid = atributos.get("id")
                # Solo ids de ARM: un estado puede gestionar tambien objetos de
                # Entra ID o de otros proveedores, que no estan en el inventario.
                if isinstance(rid, str) and rid.lower().startswith("/subscriptions/"):
                    ids.add(rid.lower())
                    tipos[tipo] = tipos.get(tipo, 0) + 1
        return {"ids": ids, "tipos": tipos, "ok": True}

    def _leer_estado(self, nombre: str, token: str) -> Dict[str, Any]:
        """`nombre` es `cuenta/contenedor/blob`, tal como se publica en el indice."""
        cuenta, contenedor, blob = nombre.split("/", 2)
        url = f"https://{cuenta}.blob.core.windows.net/{contenedor}/{blob}"
        cabeceras = {"Authorization": f"Bearer {token}", "x-ms-version": STORAGE_API_VERSION}
        try:
            respuesta = requests.get(url, headers=cabeceras, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return {"nombre": nombre, "ok": False, "motivo": type(exc).__name__, "ids": set(), "tipos": {}}

        if respuesta.status_code != 200:
            return {"nombre": nombre, "ok": False, "motivo": f"HTTP {respuesta.status_code}",
                    "ids": set(), "tipos": {}}

        datos = self._extraer(respuesta.content)
        return {
            "nombre": nombre,
            "ok": datos["ok"],
            "motivo": None if datos["ok"] else "estado ilegible",
            "ids": datos["ids"],
            "tipos": datos["tipos"],
        }

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def get_index(self, force: bool = False) -> Dict[str, Any]:
        """
        Indice de ids gestionados por Terraform.

        Devuelve `{"available", "managed_ids", "states", "states_read",
        "states_failed", "types", "read_at"}`. `managed_ids` es un conjunto de
        resource id en minusculas, listo para cruzar con Resource Graph.
        """
        with self._lock:
            if not force and self._cache and (time.time() - self._cached_at) < TTL_SECONDS:
                return self._cache

        vacio = {
            "available": False,
            "managed_ids": set(),
            "states": [],
            "states_read": 0,
            "states_failed": 0,
            "types": {},
            "read_at": None,
            "account": ACCOUNT,
            "container": CONTAINER,
        }
        if not ENABLED:
            return {**vacio, "reason": "deshabilitado"}

        token = self._token()
        if not token:
            return {**vacio, "reason": "sin credenciales de Azure"}

        # Una cuenta inaccesible no invalida las demas: se anota y se sigue.
        nombres: List[str] = []
        fallos_listado: List[str] = []
        for cuenta, contenedor in SOURCES:
            try:
                blobs = self._listar_blobs(token, cuenta, contenedor)
            except Exception as exc:
                print(f"[TfStateService] No se pudieron listar los estados: {exc}")
                fallos_listado.append(str(exc)[:160])
                continue
            nombres.extend(
                f"{cuenta}/{contenedor}/{b}" for b in blobs
                if not any(b.startswith(p) for p in EXCLUDE_PREFIXES)
            )
        if fallos_listado and not nombres:
            return {**vacio, "reason": "; ".join(fallos_listado)}

        resultados: List[Dict[str, Any]] = []
        if nombres:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(nombres))) as executor:
                futuros = [executor.submit(self._leer_estado, n, token) for n in nombres]
                for futuro in futuros:
                    try:
                        resultados.append(futuro.result())
                    except Exception as exc:
                        resultados.append({"nombre": "?", "ok": False, "motivo": str(exc)[:80],
                                           "ids": set(), "tipos": {}})

        gestionados: Set[str] = set()
        tipos: Dict[str, int] = {}
        for r in resultados:
            gestionados |= r["ids"]
            for tipo, n in r["tipos"].items():
                tipos[tipo] = tipos.get(tipo, 0) + n

        indice = {
            "available": any(r["ok"] for r in resultados),
            "managed_ids": gestionados,
            # Se publica el detalle por estado —sin un solo atributo— para que
            # el panel pueda decir sobre que se calculo la cobertura.
            "states": [
                {"name": r["nombre"], "ok": r["ok"], "resources": len(r["ids"]),
                 "reason": r["motivo"]}
                for r in sorted(resultados, key=lambda x: x["nombre"])
            ],
            "states_read": sum(1 for r in resultados if r["ok"]),
            "states_failed": sum(1 for r in resultados if not r["ok"]),
            "types": tipos,
            "sources_failed": fallos_listado,
            "read_at": time.time(),
            "account": ACCOUNT,
            "container": CONTAINER,
        }

        with self._lock:
            self._cache = indice
            self._cached_at = time.time()
        return indice

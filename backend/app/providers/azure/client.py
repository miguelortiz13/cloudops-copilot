"""
Cliente de Azure: credenciales y consultas a Resource Graph.

Extraido de `app/agents/azure_agent.py`, donde convivia con el chat: los
servicios solo necesitaban esto (consultar Resource Graph, saber si hay
conexion y reutilizar las credenciales), y depender del agente entero los
ataba al modelo de lenguaje. Es la primera pieza de la capa de proveedores
(ADR 0006): el resto del sistema deberia llegar a Azure solo a traves de aqui.

Los nombres de los metodos se conservan para no cambiar el contrato con los
servicios ni con los dobles de las pruebas.
"""

import os
import threading
import time
from typing import Any, Dict, List, Optional

# Imports del SDK a nivel de modulo para evitar bloqueos del import lock entre hilos.
try:
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    HAS_AZURE_SDK = True
except ImportError:
    HAS_AZURE_SDK = False


class AzureClient:
    def __init__(self, connect: bool = True):
        self.azure_connected = False
        self.rg_client = None
        self.azure_credentials = None

        # Cache de consultas KQL: el panel y el chat repiten las mismas.
        self._cache: Dict[Any, Any] = {}
        self._cache_ttl = 900
        self._lock = threading.Lock()

        if connect:
            self.connect_azure()

    # Scope de ARM: si se obtiene un token para el, la identidad funciona.
    _ARM_SCOPE = "https://management.azure.com/.default"

    def connect_azure(self):
        """
        Autentica contra Azure y confirma que la identidad obtiene un token.

        Orden de preferencia:
        1. Service Principal explicito (AZURE_READER_* o AZURE_CLIENT_*).
        2. DefaultAzureCredential: identidad administrada en Azure (sin
           secretos) o la sesion de `az login` en desarrollo.

        Antes se marcaba la conexion como activa solo por construir el objeto
        de credenciales, sin pedir un token: el health check decia "ok" aunque
        cada consulta fallara despues. Ahora se pide uno al conectar.
        """
        tenant_id = os.getenv("AZURE_TENANT_ID")
        client_id = os.getenv("AZURE_READER_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("AZURE_READER_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")

        try:
            if tenant_id and client_id and client_secret:
                print("Autenticando con Service Principal...")
                self.azure_credentials = ClientSecretCredential(
                    tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
                )
            else:
                print("Autenticando con DefaultAzureCredential (identidad administrada o az login)...")
                # `az` puede tardar varios segundos en emitir un token (en WSL,
                # ~8 s); el limite por defecto de 10 s lo deja al borde.
                self.azure_credentials = DefaultAzureCredential(
                    process_timeout=int(os.getenv("AZURE_CLI_TIMEOUT_SECONDS", "30")),
                    managed_identity_client_id=os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID") or None,
                )
            self.azure_credentials.get_token(self._ARM_SCOPE)
            self.rg_client = ResourceGraphClient(self.azure_credentials)
            self.azure_connected = True
            print("✅ Conectado a Azure.")
        except Exception as e:
            print(f"⚠️ Sin conexion autenticada con Azure: {str(e).splitlines()[0]}")
            self.azure_connected = False
            self.rg_client = None

    def query_azure_resource_graph(
        self,
        query: str,
        bypass_cache: bool = False,
        subscriptions: Optional[List[str]] = None,
        raise_errors: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Consulta Resource Graph con KQL, usando la cache si corresponde.

        Por defecto un error devuelve `[]`: el panel prefiere una tabla vacia a
        una pagina rota. Los recolectores pasan `raise_errors=True`, porque para
        ellos "fallo" y "no hay resultados" significan cosas opuestas: un
        hallazgo que no aparece se marca resuelto, y eso solo es cierto si la
        consulta respondio.
        """
        if not self.azure_connected or not self.rg_client:
            if raise_errors:
                raise RuntimeError("Sin conexion autenticada con Azure.")
            return []
            
        now = time.time()
        
        # Include subscriptions list in cache key to prevent cross-subscription collisions
        cache_key = (query, tuple(subscriptions) if subscriptions else None)
        with self._lock:
            if not bypass_cache and cache_key in self._cache:
                cache_time, data = self._cache[cache_key]
                if now - cache_time < self._cache_ttl:
                    return data
            
        try:
            if subscriptions is None:
                sub_id = os.getenv("AZURE_SUBSCRIPTION_ID")
                subscriptions_list = [sub_id] if sub_id else []
            else:
                subscriptions_list = subscriptions
            
            all_results = []
            skip_token = None
            
            while True:
                options = QueryRequestOptions(result_format="ObjectArray", skip_token=skip_token) if skip_token else QueryRequestOptions(result_format="ObjectArray")
                request = QueryRequest(
                    subscriptions=subscriptions_list,
                    query=query,
                    options=options
                )
                
                response = self.rg_client.resources(request)
                if response.data:
                    all_results.extend(response.data)
                
                skip_token = getattr(response, "skip_token", None)
                if not skip_token:
                    break
            
            with self._lock:
                self._cache[cache_key] = (now, all_results)
            return all_results
        except Exception as e:
            if raise_errors:
                raise
            print(f"Error querying Resource Graph: {e}")
            return []

    def query_azure_resource_graph_page(
        self,
        query: str,
        skip: int = 0,
        top: int = 100,
        subscriptions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trae una sola ventana de resultados en lugar de recorrer todas las paginas.

        Resource Graph no admite `serialize` ni `row_number()`, asi que la
        paginacion no puede expresarse dentro del KQL: se pide con las opciones
        `skip` y `top` de la peticion. La respuesta trae ademas `total_records`,
        el total de coincidencias del filtro, con lo que no hace falta una
        segunda consulta solo para contar.

        Devuelve {"rows": [...], "total": int, "ok": bool}.
        """
        if not self.azure_connected or not self.rg_client:
            return {"rows": [], "total": 0, "ok": False}

        if subscriptions is None:
            sub_id = os.getenv("AZURE_SUBSCRIPTION_ID")
            subscriptions_list = [sub_id] if sub_id else []
        else:
            subscriptions_list = subscriptions

        try:
            options = QueryRequestOptions(
                result_format="ObjectArray", skip=skip, top=top
            )
            request = QueryRequest(
                subscriptions=subscriptions_list, query=query, options=options
            )
            response = self.rg_client.resources(request)
            return {
                "rows": list(response.data or []),
                "total": int(getattr(response, "total_records", 0) or 0),
                "ok": True,
            }
        except Exception as e:
            print(f"Error querying Resource Graph (paged): {e}")
            return {"rows": [], "total": 0, "ok": False}

    def get_resource_groups(self, subscriptions: Optional[List[str]] = None) -> List[str]:
        """Fetches all resource group names from Azure in real-time."""
        if not self.azure_connected:
            return []
        try:
            kql = "resourcecontainers | where type == 'microsoft.resources/subscriptions/resourcegroups' | project name"
            results = self.query_azure_resource_graph(kql, subscriptions=subscriptions)
            return [r['name'] for r in results if r.get('name')]
        except Exception as e:
            print(f"Error fetching resource groups: {e}")
            return []

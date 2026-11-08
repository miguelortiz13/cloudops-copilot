"""
Aislamiento de las pruebas unitarias.

Las pruebas no deben depender del `backend/.env` de quien las ejecuta ni tocar
Azure. Este archivo se carga antes que cualquier modulo de `app`, asi que fija
aqui la configuracion que las pruebas asumen:

- `CLOUDOPS_SKIP_DOTENV` impide que `app.core.config` lea el `.env` local.
- El esquema de tags es el que usan los fixtures; las pruebas lo declaran en
  vez de heredar el valor por defecto, que puede cambiar.
- Sin credenciales de Azure ni base de datos en el entorno.
"""

import os

os.environ["CLOUDOPS_SKIP_DOTENV"] = "1"
os.environ["MANDATORY_TAGS"] = "Customer,Tenant,Platform,Product,Suite,Environment"
os.environ["SHOWBACK_TAGS"] = "Customer,Product,Suite,Environment"
os.environ.setdefault("MICROSOFT_APP_ID", "00000000-0000-0000-0000-000000000001")
for _var in ("AZURE_CLIENT_SECRET", "AZURE_READER_CLIENT_SECRET", "TFSTATE_ACCOUNT", "DATA_DIR",
             "DATABASE_URL", "DB_SERVER", "DB_NAME"):
    os.environ.pop(_var, None)


# CLOUDOPS_TEST_DATE=2027-06-01 corre la suite con el reloj en esa fecha (y avanzando): así se
# encuentran las pruebas que mezclan fechas fijas con la de hoy antes de que rompan solas.
if os.environ.get("CLOUDOPS_TEST_DATE"):
    import time_machine

    time_machine.travel(os.environ["CLOUDOPS_TEST_DATE"] + "T12:00:00+00:00", tick=True).start()


try:
    import pytest

    @pytest.fixture(autouse=True)
    def _sin_conexion_a_azure(monkeypatch):
        """
        Ninguna prueba unitaria se conecta a Azure, aunque haya una sesion de
        `az login` en la maquina: si un camino construye los servicios reales
        (por ejemplo, al resolver dependencias antes de un 403), el cliente
        queda desconectado en vez de pedir un token.
        """
        from app.providers.azure.client import AzureClient

        monkeypatch.setattr(AzureClient, "connect_azure", lambda self: None)

    @pytest.fixture(autouse=True)
    def _ajustes_aislados(monkeypatch, tmp_path):
        """Ajustes y silencios de cada prueba en su carpeta: un ajustes.json local no las afecta."""
        from app.core import ajustes

        monkeypatch.setattr(ajustes, "_ruta", lambda: tmp_path / "ajustes.json")
        # Guardar ajustes cambia estas listas de config en su lugar: cada prueba las deja como estaban.
        from app.core import config

        tags, showback = list(config.MANDATORY_TAGS), list(config.SHOWBACK_TAGS)
        topes = config.LLM_MAX_REQUESTS_PER_HOUR, config.LLM_MAX_REQUESTS_PER_DAY
        yield
        config.MANDATORY_TAGS[:], config.SHOWBACK_TAGS[:] = tags, showback
        config.LLM_MAX_REQUESTS_PER_HOUR, config.LLM_MAX_REQUESTS_PER_DAY = topes
except ImportError:  # las pruebas de integracion se ejecutan sin pytest
    pass

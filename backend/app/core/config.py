"""
Configuracion central de CloudOps Copilot.

Todo valor que dependa de la organizacion que opera la plataforma —sus tags
obligatorias, su nombre, la URL del panel, donde guarda el estado de Terraform—
se lee aqui desde variables de entorno. El resto del codigo importa estas
constantes en lugar de llevar valores escritos a mano, de modo que adoptar la
plataforma en otro tenant es cuestion de un `.env`, no de editar codigo.

El `.env` se carga al importar este modulo. Varios servicios (`auth.py`,
`bot_auth.py`, `cost_service.py`) leen sus variables en tiempo de import, asi
que `app.main` importa este modulo antes que cualquier otro. `load_dotenv` no
sobrescribe variables ya definidas en el entorno, de modo que en un contenedor
o en App Service manda la configuracion de la plataforma.
"""

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Las pruebas fijan su propia configuracion (tests/conftest.py).
if not os.getenv("CLOUDOPS_SKIP_DOTENV"):
    load_dotenv(BACKEND_DIR / ".env")


def _lista(nombre: str, por_defecto: str) -> List[str]:
    """Lee una lista separada por comas, descartando elementos vacios."""
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        valor = por_defecto
    return [v.strip() for v in valor.split(",") if v.strip()]


def _bool(nombre: str, por_defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return por_defecto
    return valor.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Identidad de la plataforma
# ---------------------------------------------------------------------------
APP_NAME = os.getenv("APP_NAME", "CloudOps Copilot")
APP_VERSION = "2.4.1"
# Nombre con el que se presentan los agentes ("Agente FinOps de <ORG_NAME>").
ORG_NAME = os.getenv("ORG_NAME", "tu organización")

# ---------------------------------------------------------------------------
# Gobernanza de tags
# ---------------------------------------------------------------------------
# Tags que todo recurso debe llevar para considerarse conforme. El esquema por
# defecto es el de docs/governance/tagging-policy.md; cambiarlo aqui cambia el
# KPI de cumplimiento, la matriz de tags, el filtro de Shadow IT y las
# plantillas de Terraform a la vez.
MANDATORY_TAGS = _lista("MANDATORY_TAGS", "Environment,Project,ManagedBy")
# Dimensiones por las que FinOps atribuye el gasto (showback / chargeback).
SHOWBACK_TAGS = _lista("SHOWBACK_TAGS", "Project,Environment")

# ---------------------------------------------------------------------------
# Red y frontend
# ---------------------------------------------------------------------------
# URL publica del panel. Se usa en los enlaces de las tarjetas de Teams.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# Origenes permitidos por CORS. Nunca "*": el API se usa con credenciales.
ALLOWED_ORIGINS = _lista(
    "ALLOWED_ORIGINS",
    ",".join([FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"]),
)

# ---------------------------------------------------------------------------
# Almacenamiento persistente
# ---------------------------------------------------------------------------
# Directorio donde la plataforma guarda lo que debe sobrevivir a un reinicio:
# la cache de costos, la serie historica de KPIs, el Excel maestro del pipeline
# de inventario y sus snapshots. En Azure es un File Share montado.
# EXCEL_STORAGE_DIR se acepta por compatibilidad con despliegues anteriores.
DATA_DIR = Path(
    os.getenv("DATA_DIR") or os.getenv("EXCEL_STORAGE_DIR") or (BACKEND_DIR / "data")
)
INVENTORY_EXCEL = DATA_DIR / "Azure_IaC_Inventario.xlsx"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
PIPELINE_DIR = BACKEND_DIR / "pipelines" / "inventory"

# ---------------------------------------------------------------------------
# Terraform
# ---------------------------------------------------------------------------
# Cuenta de almacenamiento donde viven los estados de Terraform de la
# organizacion. Vacia = la cobertura real de IaC queda desactivada.
TFSTATE_ACCOUNT = os.getenv("TFSTATE_ACCOUNT", "").strip()
TFSTATE_CONTAINER = os.getenv("TFSTATE_CONTAINER", "tfstate")
# Admite varias cuentas: "cuenta1,cuenta2/otro-contenedor". Sin contenedor
# explicito se usa TFSTATE_CONTAINER. Es lo normal cuando cada proyecto guarda
# su estado en su propia cuenta.
TFSTATE_SOURCES = [
    (fuente.split("/", 1)[0].strip(), (fuente.split("/", 1)[1] if "/" in fuente else TFSTATE_CONTAINER).strip())
    for fuente in TFSTATE_ACCOUNT.split(",") if fuente.strip()
]
# Prefijo de la llave del estado en el codigo HCL que genera el modulo IaC:
# <prefijo>/<suscripcion>/<ambiente>/<dominio>/terraform.tfstate
IAC_STATE_KEY_PREFIX = os.getenv("IAC_STATE_KEY_PREFIX", "platform/azure").strip("/")
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "eastus2")

# ---------------------------------------------------------------------------
# Motor cognitivo
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def ensure_data_dirs() -> None:
    """Crea el directorio de datos si no existe. Nunca detiene el arranque."""
    try:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - depende del sistema de archivos
        print(f"[config] No se pudo preparar {DATA_DIR}: {exc}")

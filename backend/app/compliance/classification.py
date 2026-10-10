"""
Clasificacion de activos ISO 27001 (controles A.5.9 y A.5.12).

Reemplaza a la hoja `12_inventario_iso` del Excel del pipeline: la misma
regla, ahora sobre el inventario de la base y con dos mejoras:

* Se explica: cada clasificacion lleva el motivo con el que se decidio.
* Se puede corregir: un operador fija una clasificacion manual (con su motivo,
  auditada) y el recolector la respeta hasta que alguien la devuelva a la
  automatica.

La regla automatica, por ambiente y por lo que guarda el recurso:

| Ambiente      | Datos o llaves | Computo o red | Resto       |
|---------------|----------------|---------------|-------------|
| Produccion    | Confidencial   | Restringido   | Restringido |
| Otro          | Restringido    | Uso interno   | Uso interno |

Confidencialidad, integridad y disponibilidad van de 1 a 3; la criticidad es
su suma (3 a 9). Todo activo de produccion requiere analisis de riesgo.
"""

from typing import Any, Dict, NamedTuple, Optional

from app.services import governance
from app.services.inventory_service import INVALID_TAG_VALUES, PRODUCTION_ENVIRONMENTS

CLASES = ("Confidencial", "Restringido", "Uso interno")

TIPOS_DE_DATOS = ("microsoft.sql/", "microsoft.keyvault/", "microsoft.storage/", "microsoft.documentdb/",
                  "microsoft.dbforpostgresql/", "microsoft.dbformysql/", "microsoft.cache/")
TIPOS_DE_COMPUTO_Y_RED = ("microsoft.containerservice/", "microsoft.compute/virtualmachines",
                          "microsoft.web/sites", "microsoft.network/networksecuritygroups", "microsoft.app/")


class Clasificacion(NamedTuple):
    classification: str
    confidentiality: int
    integrity: int
    availability: int
    risk_required: bool
    reason: str

    @property
    def score(self) -> int:
        return self.confidentiality + self.integrity + self.availability


def _tags(tags: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {str(k).lower(): str(v).strip() for k, v in (tags or {}).items() if v is not None}


def ambiente(tags: Optional[Dict[str, Any]]) -> str:
    return _tags(tags).get("environment", "").lower()


def es_produccion(tags: Optional[Dict[str, Any]]) -> bool:
    return ambiente(tags) in PRODUCTION_ENVIRONMENTS


def custodio(tags: Optional[Dict[str, Any]], creado_por: Optional[str] = None) -> Optional[str]:
    """El responsable declarado en las tags; si no hay, quien lo creo."""
    t = _tags(tags)
    for clave in governance.OWNER_TAG_KEYS:
        valor = t.get(clave, "")
        if valor and valor.lower() not in INVALID_TAG_VALUES:
            return valor
    return creado_por or None


def clasificar(tipo_nativo: str, tags: Optional[Dict[str, Any]]) -> Clasificacion:
    tipo = (tipo_nativo or "").lower()
    prod = es_produccion(tags)
    datos = tipo.startswith(TIPOS_DE_DATOS)
    computo = tipo.startswith(TIPOS_DE_COMPUTO_Y_RED)
    donde = "Producción" if prod else ("Ambiente " + ambiente(tags) if ambiente(tags) else "Sin ambiente declarado")

    if prod and datos:
        return Clasificacion("Confidencial", 3, 3, 3, True, f"{donde} · guarda datos o llaves")
    if prod and computo:
        return Clasificacion("Restringido", 2, 3, 3, True, f"{donde} · cómputo o red expuesta")
    if prod:
        return Clasificacion("Restringido", 2, 2, 2, True, f"{donde}")
    if datos:
        return Clasificacion("Restringido", 2, 2, 2, False, f"{donde} · guarda datos o llaves")
    return Clasificacion("Uso interno", 1, 1, 1, False, donde)

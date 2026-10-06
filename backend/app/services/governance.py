"""
Reglas de gobernanza: una sola definicion de Shadow IT, custodio y evidencia IaC.

Que se considera "creado fuera de IaC" estaba escrito tres veces y las tres
diferian: el inventario buscaba seis claves de tag y seis valores; el resumen del
agente contaba solo `provisioning_method`, `provisioned_by` y `created_by` con el
valor exacto 'terraform'; y el motor de reglas del chat filtraba por dos de esas
claves con `!=`, que en KQL tampoco es lo contrario de la condicion anterior. El
mismo tenant daba tres cifras de cobertura IaC segun donde se preguntara.

Por que cambio la regla
-----------------------
La definicion anterior marcaba como candidato a Shadow IT todo recurso sin tag
de IaC que ademas no fuera conforme **o** no tuviera `managedBy`. Medido contra
produccion, eso senalaba 545 de 602 recursos (90.5%), y de esos, 499 tenian las
seis tags obligatorias completas: los marcaba solo por no tener `managedBy`.

`managedBy` no dice nada sobre como se aprovisiono un recurso. Azure lo rellena
unicamente cuando otro recurso es el dueno del primero —una VM de un conjunto de
escala, un disco de un nodo de AKS—, y en este tenant lo tiene el 2.5% del
inventario. Un storage account creado por Terraform nunca lo va a tener. Usar su
ausencia como senal convertia la metrica en "casi todo el inventario", y un panel
que senala el 90% no dirige ninguna accion: es ruido con formato de alerta.

La regla nueva exige cuatro ausencias independientes:

1. sin evidencia de IaC en las tags,
2. no derivado de otro recurso de Azure (el propio `managedBy`, los grupos de
   nodos de AKS/Databricks, o tipos que Azure crea solo, como las reglas de
   deteccion inteligente que acompanan a Application Insights),
3. sin custodio identificable en ninguna de las claves de propiedad que usa la
   organizacion,
4. con las tags obligatorias incompletas.

Sobre el mismo tenant eso deja 35 recursos (5.8%), y la muestra son justo los que
delatan el portal: VNets con nombres autogenerados (`rg_dev_paasvnet724`), sus
NSG basicos (`basicNsg...`), extensiones de VM y reglas de autoescalado sueltas.

Evidencia probada, no heuristica
--------------------------------
Ninguna regla sobre tags puede *demostrar* que algo se creo a mano. La tabla
`resourcechanges` de Resource Graph si: registra quien creo cada recurso. Una
identidad con arroba es una persona operando el portal o la CLI; un GUID es un
service principal, es decir automatizacion. Eso es Shadow IT probado en lugar de
sospechado, con una limitacion que hay que declarar siempre: Azure solo conserva
esos eventos unos catorce dias, asi que la evidencia cubre lo reciente y nunca el
inventario historico. Ver `KQL_CREACIONES` y `InventoryService.get_manual_creations`.
"""

import os
from typing import Dict, List, Optional

# --- Evidencia de aprovisionamiento por IaC ---------------------------------
# Claves de tag que delatan que el recurso lo creo una herramienta.
IAC_TAG_KEYS = [
    "managedby", "iac", "terraform", "provisioningtool",
    "provisioned_by", "provisioning_method", "created_by",
]

# Valores que delatan lo mismo, este donde este la clave.
IAC_TAG_VALUES = ["terraform", "iac", "bicep", "arm", "pulumi", "crossplane"]

# Valores que, aun bajo una clave de IaC, declaran lo contrario. Sin esto un
# esquema que exige la tag `ManagedBy` contaria `ManagedBy=Manual` como IaC.
NON_IAC_TAG_VALUES = ["manual", "portal", "clickops", "none", "n/a", ""]

# --- Custodio ---------------------------------------------------------------
# Un solo conjunto de claves de propiedad. Antes habia dos listas distintas
# —una para el puntaje de completitud y otra para el custodio mostrado— y
# ninguna incluia las claves que este tenant usa de verdad: con las seis
# originales solo 5 de 602 recursos tenian dueno (0.8%); anadiendo ownertech,
# ownerfunc, author y createdby son 91 (15.1%).
OWNER_TAG_KEYS = [
    "owner", "responsable", "team", "squad", "contact", "custodio",
    "ownertech", "ownerfunc", "author", "createdby",
]

# --- Recursos derivados de otro recurso de Azure ----------------------------
# No son Shadow IT ni deuda de gobernanza: los crea la plataforma como parte de
# otro recurso, y etiquetarlos a mano no esta ni siquiera en manos del equipo.
DERIVED_RG_PREFIXES = ["mc_", "databricks-rg", "networkwatcherrg", "aksinfra_"]

DERIVED_TYPES = [
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.insights/webtests",
]


# ---------------------------------------------------------------------------
# Predicados en Python
# ---------------------------------------------------------------------------

def tiene_evidencia_iac(tags_lower: Dict[str, str]) -> bool:
    """
    Si alguna tag declara que el recurso lo aprovisiono una herramienta.

    Es la evidencia debil: constata que alguien lo etiqueto. La fuerte es
    `esta_en_estado`, que lo comprueba contra el estado real de Terraform.
    """
    for clave in IAC_TAG_KEYS:
        if clave in tags_lower and str(tags_lower[clave] or "").strip().lower() not in NON_IAC_TAG_VALUES:
            return True
    return any(valor in IAC_TAG_VALUES for valor in tags_lower.values())


def esta_en_estado(resource_id: str, managed_ids) -> bool:
    """
    Si el recurso aparece en algun estado de Terraform.

    Evidencia dura: no hay heuristica de por medio. Solo exonera —un recurso en
    el estado esta gestionado, seguro—, nunca acusa: que no aparezca puede
    significar que su equipo guarda el estado en otra cuenta, no que se creara a
    mano. Por eso la regla de tags sigue siendo la que decide a quien senalar.
    """
    if not managed_ids:
        return False
    return str(resource_id or "").lower() in managed_ids


def tiene_custodio(tags_lower: Dict[str, str], invalidos: set) -> bool:
    """Si alguna tag identifica a un responsable con un valor util."""
    for clave in OWNER_TAG_KEYS:
        valor = str(tags_lower.get(clave, "")).strip()
        if valor and valor.lower() not in invalidos:
            return True
    return False


def es_derivado(managed_by: Optional[str], resource_group: str, tipo: str) -> bool:
    """Si el recurso lo creo y lo gobierna otro recurso de Azure."""
    if str(managed_by or "").strip():
        return True
    rg = str(resource_group or "").lower()
    if any(rg.startswith(prefijo) for prefijo in DERIVED_RG_PREFIXES):
        return True
    return str(tipo or "").lower() in DERIVED_TYPES


# ---------------------------------------------------------------------------
# Los mismos predicados en KQL
# ---------------------------------------------------------------------------
#
# `_t` es el bag de tags con claves y valores en minusculas y `_json` su
# representacion textual, ambos definidos por el preludio que consume estas
# expresiones. La equivalencia con las funciones de arriba la verifica
# tests/test_inventory_kpis.py contra el inventario real.


def kql_tiene_iac() -> str:
    negativos = ", ".join(f"'{v}'" for v in NON_IAC_TAG_VALUES)
    claves = " or ".join(
        f"(array_index_of(bag_keys(_t), '{k}') >= 0 and trim(' ', tostring(_t['{k}'])) !in ({negativos}))"
        for k in IAC_TAG_KEYS
    )
    # En el JSON ya minusculizado un valor exacto aparece como :"terraform", lo
    # que ancla la busqueda a la posicion de valor y no confunde con una clave
    # homonima.
    valores = " or ".join(f'_json has \':"{v}"\'' for v in IAC_TAG_VALUES)
    return f"(({claves}) or ({valores}))"


# Cuantos ids caben en la consulta antes de que el literal se vuelva
# impracticable. Con mas que esto se prescinde de la evidencia del estado en el
# agregado y se declara, en vez de partir la consulta en pedazos.
MAX_IDS_EN_CONSULTA = int(os.getenv("TFSTATE_MAX_IDS_KQL", "2000"))


def kql_gestionado_por_terraform(managed_ids) -> str:
    """
    Expresion KQL que indica si el recurso aparece en un estado de Terraform.

    La evidencia del estado se inyecta como literal para que el agregado del
    panel y el listado apliquen exactamente la misma regla. Sin esto, el KPI se
    calcularia con tags y la tabla con estados, y volveriamos a tener dos
    verdades para la misma pregunta.
    """
    ids = [i for i in (managed_ids or []) if i]
    if not ids or len(ids) > MAX_IDS_EN_CONSULTA:
        return "false"
    literal = ", ".join("'" + str(i).replace("'", "") + "'" for i in sorted(ids))
    return f"(tolower(id) in ({literal}))"


def kql_tiene_custodio(invalidos_kql: str) -> str:
    return "(" + " or ".join(
        f"(isnotempty(trim(' ', tostring(_t['{k}']))) and "
        f"trim(' ', tostring(_t['{k}'])) !in ({invalidos_kql}))"
        for k in OWNER_TAG_KEYS
    ) + ")"


def kql_es_derivado() -> str:
    prefijos = " or ".join(
        f"tolower(resourceGroup) startswith '{p}'" for p in DERIVED_RG_PREFIXES
    )
    tipos = ", ".join(f"'{t}'" for t in DERIVED_TYPES)
    return f"(isnotempty(tostring(managedBy)) or ({prefijos}) or tolower(type) in ({tipos}))"


# Recursos creados en la ventana que Azure conserva, con la identidad que los
# creo. Es la unica evidencia dura de aprovisionamiento manual que hay sin
# permisos adicionales: `resourcechanges` la cubre el rol Reader.
KQL_CREACIONES = (
    "resourcechanges "
    "| extend _c = parse_json(properties) "
    "| extend quien = tostring(_c.changeAttributes.changedBy), "
    "         tipoCambio = tostring(_c.changeType), "
    "         cuando = todatetime(_c.changeAttributes.timestamp) "
    "| where tipoCambio == 'Create' "
    "| extend esPersona = quien contains '@' "
    "| project id = tostring(_c.targetResourceId), "
    "          tipoRecurso = tostring(_c.targetResourceType), "
    "          quien, cuando, esPersona "
    "| order by cuando desc"
)


# ---------------------------------------------------------------------------
# Tags obligatorias en KQL
# ---------------------------------------------------------------------------
#
# Las consultas del agente evaluaban las seis tags de un esquema concreto con
# expresiones escritas a mano. Se generan desde `config.MANDATORY_TAGS` para que
# el chat y el panel usen el mismo esquema que la organizacion configure.


def _slug_tag(tag: str) -> str:
    return "".join(c for c in tag.lower() if c.isalnum() or c == "_")


def kql_extends_tags_presentes(tags: List[str]) -> str:
    """Una columna `has_<tag>` por tag, sin distinguir mayusculas en la clave."""
    lineas = []
    for tag in tags:
        variantes = {tag, tag.lower(), tag.upper()}
        cond = " or ".join(f"isnotnull(tags['{v}'])" for v in sorted(variantes))
        lineas.append(f"| extend has_{_slug_tag(tag)} = {cond} ")
    return "".join(lineas)


def kql_todas_presentes(tags: List[str]) -> str:
    return "(" + " and ".join(f"has_{_slug_tag(t)}" for t in tags) + ")" if tags else "true"


def kql_conteo_faltantes(tags: List[str]) -> str:
    """Agregados `missing_<tag>` para un `summarize`."""
    return ", ".join(f"missing_{_slug_tag(t)} = countif(not(has_{_slug_tag(t)}))" for t in tags)


def columna_faltantes(tag: str) -> str:
    return f"missing_{_slug_tag(tag)}"


# ---------------------------------------------------------------------------
# Que ids de un estado de Terraform puede ver el inventario
# ---------------------------------------------------------------------------
#
# Un estado gestiona mucho mas que recursos: contenedores y tablas de storage,
# role assignments, budgets, el propio resource group, secretos de Key Vault.
# Ninguno esta en la tabla `resources` de Resource Graph. Tratarlos como
# recursos hacia que la cobertura los diera por "borrados fuera de Terraform":
# en un proyecto vivo, 37 de 57 ids salian como obsoletos y ninguno lo era.

def es_recurso_inventariable(resource_id: str) -> bool:
    """
    Si el id corresponde a un recurso de primer nivel de la tabla `resources`.

    Forma esperada: /subscriptions/<s>/resourcegroups/<rg>/providers/<ns>/<tipo>/<nombre>
    Quedan fuera los subrecursos (mas pares tipo/nombre), los recursos de
    extension (un segundo `/providers/`), los grupos de recursos y los recursos
    de nivel de suscripcion.
    """
    partes = str(resource_id or "").strip("/").lower().split("/")
    return (
        len(partes) == 8
        and partes[0] == "subscriptions"
        and partes[2] == "resourcegroups"
        and partes[4] == "providers"
    )

"""
Contexto que el agente le da al modelo: datos del dominio y su presupuesto.

Funciones de módulo que reciben el agente (como rule_answers): leen sus
servicios compartidos con el panel y sus límites (`PRESUPUESTO_*`, `MAX_*`,
que siguen en la clase para poder ajustarse por instancia).
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.services import kql


def tags_como_dict(tags: Any) -> Dict[str, Any]:
    """
    Normaliza los tags de un recurso, vengan como diccionario o serializados.

    Un recurso sin tags llega como la cadena `"null"` —`search_resources`
    hace `json.dumps(None)`— y `json.loads` la convierte de vuelta en `None`,
    no en un diccionario. El codigo que seguia llamaba `.items()` sobre ese
    `None` y reventaba dentro del `try` general de `ask()`, que lo
    interpretaba como un fallo del modelo y respondia con el motor de
    reglas. Es decir: bastaba un solo recurso sin etiquetar en la muestra
    —lo habitual— para que el agente dejara de usar IA sin decirlo.
    """
    if isinstance(tags, dict):
        return tags
    if isinstance(tags, str):
        try:
            cargado = json.loads(tags)
        except Exception:
            return {}
        return cargado if isinstance(cargado, dict) else {}
    return {}


def acotar(valor: Any, limite: int) -> Any:
    """Recorta una lista dejando constancia de cuantos elementos tenia."""
    if not isinstance(valor, list) or len(valor) <= limite:
        return valor
    return {
        "muestra": valor[:limite],
        "total": len(valor),
        "truncado": True,
        "nota": (
            f"Se incluyen {limite} de {len(valor)} elementos. "
            "El total es exacto; para ver el resto hay que acotar la pregunta."
        ),
    }


def acotar_contexto(agente, context_data: Dict[str, Any], question: str
) -> Dict[str, Any]:
    """
    Aplica el presupuesto a todo el contexto antes de serializarlo.

    Los grupos de recursos reciben trato aparte: en lugar de mandar los
    cientos que tiene el tenant, viajan los que la pregunta menciona mas una
    muestra, porque su utilidad es que el agente reconozca el nombre que el
    usuario escribio.
    """
    acotado: Dict[str, Any] = {}
    pregunta = (question or "").lower()

    for clave, valor in context_data.items():
        if clave == "all_resource_groups" and isinstance(valor, list):
            mencionados = [rg for rg in valor if rg and rg.lower() in pregunta]
            resto = [rg for rg in valor if rg not in mencionados]
            seleccion = mencionados + resto[: agente.MAX_GRUPOS_DE_RECURSOS]
            acotado[clave] = (
                seleccion
                if len(valor) <= agente.MAX_GRUPOS_DE_RECURSOS
                else {
                    "muestra": seleccion,
                    "total": len(valor),
                    "truncado": True,
                    "nota": (
                        "Incluye los grupos de recursos citados en la pregunta "
                        f"mas una muestra; el tenant tiene {len(valor)}."
                    ),
                }
            )
        elif clave == "target_resource_group_resources":
            acotado[clave] = agente._acotar(valor, agente.MAX_RECURSOS_DE_RG)
        elif clave == "security_findings":
            # Vienen ordenados por severidad, asi que el recorte conserva
            # siempre lo mas grave primero.
            acotado[clave] = agente._acotar(valor, agente.MAX_HALLAZGOS)
        elif clave == "relevant_resources_sample":
            acotado[clave] = agente._acotar(valor, agente.MUESTRA_POR_LISTA)
        else:
            acotado[clave] = agente._acotar(valor, agente.MUESTRA_POR_LISTA)

    return acotado


def contexto_de_dominio(agente, agent_type: str, subscriptions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Datos del dominio del agente, tomados de las mismas fuentes que el panel.

    SecOps delega en SecOpsService: asi el chat hereda las consultas
    corregidas y la severidad por alcanzabilidad, en vez de la copia paralela
    que tenia el agente —la que marcaba el 96% de las cuentas de
    almacenamiento como expuestas y todos los Key Vaults del tenant—. FinOps
    usa el catalogo compartido de consultas (services/kql.py).
    """
    if agent_type == "secops":
        # Si el servicio de riesgo esta disponible, los hallazgos llegan ya
        # cruzados con el gasto del recurso expuesto y ordenados por
        # severidad y dinero: el chat prioriza igual que el panel.
        try:
            if agente._risk is not None:
                reporte = agente._risk.build_report(subscriptions or [])
                reporte["exposure"] = {
                    "by_severity": reporte.get("exposure_by_severity", {}),
                    "top": reporte.get("top_exposure", []),
                    "totals": reporte.get("totals", {}),
                    "coverage": reporte.get("coverage", {}),
                }
            else:
                reporte = agente._get_secops().build_report(subscriptions or [])
        except Exception as exc:
            print(f"Error construyendo el contexto de SecOps: {exc}")
            return {}
        # `findings` ya contiene, con severidad y recomendacion, los mismos
        # elementos que las listas por tipo del panel: mandar ambas cosas
        # duplicaba el contexto sin añadir un solo dato. Las IPs publicas
        # activas si viajan aparte, porque son superficie de ataque y no
        # hallazgos: el reporte las cuenta pero no las clasifica.
        contexto = {
            "security_findings": reporte.get("findings", []),
            "severity_summary": reporte.get("severity_summary", {}),
            "attack_surface_summary": reporte.get("attack_surface_summary", {}),
            "public_ips_active_list": reporte.get("public_ips_active", []),
        }
        if reporte.get("exposure"):
            contexto["cost_exposure"] = reporte["exposure"]
        return contexto

    if agent_type == "finops":
        consultas = {
            "unattached_disks_list": kql.DISCOS_HUERFANOS,
            "unassociated_ips_list": kql.IPS_SIN_ASOCIAR,
            "orphaned_nics_list": kql.NICS_HUERFANAS,
            "empty_app_plans_list": kql.APP_PLANS_VACIOS,
            "old_snapshots_list": kql.SNAPSHOTS,
            "untagged_resources_list": kql.recursos_sin_tags(25),
            "resources_by_rg": kql.RECURSOS_POR_RG,
        }
        return agente._ejecutar_en_paralelo(consultas, subscriptions)

    return {}


def ejecutar_en_paralelo(agente, consultas: Dict[str, str], subscriptions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Lanza varias consultas KQL a la vez y espera, en total, lo que marque
    `PRESUPUESTO_CONTEXTO_SEGUNDOS`.

    Una consulta que se pase de tiempo devuelve lista vacia y se anota, en
    lugar de tumbar el resto: antes, cualquier expiracion vaciaba todas las
    listas a la vez y el agente respondia como si el tenant estuviera vacio.
    """
    resultados: Dict[str, Any] = {nombre: [] for nombre in consultas}
    incompletas: List[str] = []

    with ThreadPoolExecutor(max_workers=max(1, len(consultas))) as executor:
        futuros = {
            nombre: executor.submit(
                agente.azure.query_azure_resource_graph, consulta, False, subscriptions
            )
            for nombre, consulta in consultas.items()
        }
        limite = time.monotonic() + agente.PRESUPUESTO_CONTEXTO_SEGUNDOS
        for nombre, futuro in futuros.items():
            restante = max(0.1, limite - time.monotonic())
            try:
                resultados[nombre] = futuro.result(timeout=restante) or []
            except Exception as exc:
                incompletas.append(nombre)
                print(f"Consulta de contexto '{nombre}' sin resultado: {exc}")

    if incompletas:
        resultados["consultas_incompletas"] = incompletas
    return resultados

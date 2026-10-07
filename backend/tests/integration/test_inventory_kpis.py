"""
Prueba de fidelidad de los KPIs del inventario.

Los KPIs se calculan ahora con agregados de Azure Resource Graph en lugar de
descargar el inventario completo y contarlo en Python. Esta prueba existe para
garantizar que ese cambio no altero ni un solo numero: compara, contra el mismo
inventario real, el resultado del camino nuevo (`_summary_from_kql`) contra el
de la implementacion de referencia (`get_summary_from_resources`).

La equivalencia es delicada porque hay que replicar en KQL la semantica exacta
del codigo Python: comparacion de tags sin distinguir mayusculas, valores que no
cuentan como presentes ("n/a", "tbd", "sin definir", ...), y dos conjuntos
distintos de claves de custodio segun la funcion que las use.

Requiere credenciales de Azure validas en backend/.env, porque el objetivo es
justamente contrastar contra datos reales.

Ejecutar con:

    ./.venv/bin/python3 tests/test_inventory_kpis.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from app.providers.azure import AzureClient  # noqa: E402
from app.services.inventory_service import MANDATORY_TAGS, InventoryService  # noqa: E402

# KPIs escalares que deben coincidir exactamente entre ambos caminos.
KPIS_EXACTOS = [
    "totalResources",
    "totalSubscriptions",
    "totalResourceGroups",
    "totalRegions",
    "nonCompliantResources",
    "shadowItCandidates",
    "resourcesWithoutOwnerCandidate",
    "productionResources",
    "nonProductionResources",
]

DISTRIBUCIONES = ["bySubscription", "byResourceType", "byRegion", "byEnvironment"]


def comparar(subscription_ids):
    """Ejecuta ambos caminos y devuelve (kql, referencia, tiempos)."""
    azure = AzureClient()
    if not azure.azure_connected:
        print("SALTADA: sin conexión autenticada a Azure.")
        sys.exit(0)

    servicio = InventoryService(azure)

    t0 = time.time()
    por_kql = servicio._summary_from_kql(subscription_ids, force_refresh=True)
    t_kql = time.time() - t0

    t0 = time.time()
    referencia = servicio.get_summary_from_resources(subscription_ids, force_refresh=True)
    t_ref = time.time() - t0

    return por_kql, referencia, t_kql, t_ref


def main():
    azure_tmp = AzureClient()
    servicio_tmp = InventoryService(azure_tmp)
    subs, _ = servicio_tmp.list_accessible_subscriptions()
    subscription_ids = [s["subscriptionId"] for s in subs]

    if not subscription_ids:
        print("SALTADA: el Service Principal no ve ninguna suscripción.")
        return 0

    print(f"Comparando sobre {len(subscription_ids)} suscripción(es) reales...\n")
    por_kql, referencia, t_kql, t_ref = comparar(subscription_ids)

    if por_kql is None:
        print("FALLA: el camino KQL devolvió None (Azure no respondió).")
        return 1

    fallos = 0

    print(f"{'KPI':<36} {'KQL':>10} {'referencia':>12}   resultado")
    print("-" * 76)
    for kpi in KPIS_EXACTOS:
        a, b = por_kql.get(kpi), referencia.get(kpi)
        ok = a == b
        if not ok:
            fallos += 1
        print(f"{kpi:<36} {str(a):>10} {str(b):>12}   {'coincide' if ok else '>>> DIFIERE'}")

    # El porcentaje se calcula por division, asi que se admite un desvio de
    # redondeo minimo, no una diferencia de conteo.
    pa = por_kql.get("tagCompliancePercentage", 0.0)
    pb = referencia.get("tagCompliancePercentage", 0.0)
    ok_pct = abs(pa - pb) <= 0.1
    if not ok_pct:
        fallos += 1
    print(f"{'tagCompliancePercentage':<36} {pa:>10} {pb:>12}   {'coincide' if ok_pct else '>>> DIFIERE'}")

    print()
    print("Distribuciones (top 15, se compara el conjunto de claves y sus conteos):")
    for dist in DISTRIBUCIONES:
        a = {d["key"]: d["count"] for d in por_kql.get(dist, [])}
        b = {d["key"]: d["count"] for d in referencia.get(dist, [])}
        # Solo se comparan las claves que ambos lados alcanzaron a incluir: con
        # empates en el puesto 15 el corte puede elegir claves distintas sin que
        # ninguno de los dos este mal.
        comunes = set(a) & set(b)
        difieren = {k: (a[k], b[k]) for k in comunes if a[k] != b[k]}
        faltantes = set(b) - set(a)
        if difieren:
            fallos += 1
            print(f"  >>> DIFIERE {dist}: {difieren}")
        else:
            extra = f" ({len(faltantes)} clave(s) fuera del top por empate)" if faltantes else ""
            print(f"  coincide {dist}: {len(comunes)} clave(s) verificada(s){extra}")

    print()
    print(f"tiempo camino KQL        : {t_kql:.2f}s")
    print(f"tiempo camino referencia : {t_ref:.2f}s")
    if t_kql > 0:
        print(f"aceleración              : {t_ref / t_kql:.1f}x")

    # --- Matriz de cumplimiento de tags ---
    print()
    print("Matriz de tags obligatorias:")
    azure = AzureClient()
    servicio = InventoryService(azure)
    tc_kql = servicio.get_tag_compliance(subscription_ids, force_refresh=True)
    tc_ref = servicio.get_tag_compliance_from_resources(subscription_ids, force_refresh=True)
    m_kql = {m["tag"]: (m["present"], m["missing"]) for m in tc_kql["matrix"]}
    m_ref = {m["tag"]: (m["present"], m["missing"]) for m in tc_ref["matrix"]}
    for tag in m_ref:
        ok = m_kql.get(tag) == m_ref[tag]
        if not ok:
            fallos += 1
        estado = "coincide" if ok else f">>> DIFIERE {m_kql.get(tag)} vs {m_ref[tag]}"
        print(f"  {tag:<14} presentes={m_ref[tag][0]:<5} faltantes={m_ref[tag][1]:<5} {estado}")

    # --- Paginacion y filtros ---
    print()
    print("Paginación y filtros (se comparan total e ids de la página):")
    casos = [
        ("sin filtros, pág. 1", {"page": 1, "pageSize": 25, "filters": {}}),
        ("sin filtros, pág. 3", {"page": 3, "pageSize": 25, "filters": {}}),
        ("solo no conformes", {"page": 1, "pageSize": 25, "filters": {"onlyNonCompliant": True}}),
        ("solo Shadow IT", {"page": 1, "pageSize": 25, "filters": {"onlyShadowItCandidates": True}}),
        ("búsqueda 'prod'", {"page": 1, "pageSize": 25, "filters": {"search": "prod"}}),
        (f"falta tag {MANDATORY_TAGS[0]}", {"page": 1, "pageSize": 25, "filters": {"missingTags": [MANDATORY_TAGS[0]]}}),
        (f"falta tag {MANDATORY_TAGS[-1].lower()} (minúsculas)", {"page": 1, "pageSize": 25, "filters": {"missingTags": [MANDATORY_TAGS[-1].lower()]}}),
        ("falta tag no obligatoria", {"page": 1, "pageSize": 25, "filters": {"missingTags": ["TagQueNoExiste"]}}),
    ]
    for nombre, extra in casos:
        req = {"subscriptionIds": subscription_ids, "forceRefresh": False}
        req.update(extra)
        r_kql = servicio._resources_from_kql(req)
        r_ref = servicio.get_resources_from_memory(req)
        if r_kql is None:
            fallos += 1
            print(f"  >>> {nombre}: el camino KQL devolvió None")
            continue
        ok_total = r_kql["total"] == r_ref["total"]
        ids_kql = {i["id"].lower() for i in r_kql["items"]}
        ids_ref = {i["id"].lower() for i in r_ref["items"]}
        # El orden difiere (Azure ordena por nombre, memoria por orden de llegada),
        # asi que se compara el conjunto de la pagina solo cuando cabe entero.
        ok_ids = ids_kql == ids_ref if r_ref["total"] <= extra["pageSize"] else True
        if not (ok_total and ok_ids):
            fallos += 1
            detalle = f"total {r_kql['total']} vs {r_ref['total']}"
            if not ok_ids:
                detalle += f"; {len(ids_kql ^ ids_ref)} id(s) distintos"
            print(f"  >>> DIFIERE {nombre}: {detalle}")
        else:
            print(f"  coincide {nombre}: total={r_ref['total']}, página={len(r_ref['items'])}")

    print()
    if fallos:
        print(f"RESULTADO: {fallos} discrepancia(s). NO migrar hasta resolverlas.")
        return 1
    print("RESULTADO: los dos caminos producen los mismos números.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

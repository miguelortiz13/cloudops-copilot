"""
Pruebas del contexto que el agente le pasa al modelo.

Cubren las dos reglas que hacen que el chat sea fiable:

1. **Una sola definicion de cada regla de dominio.** El agente y el panel deben
   leer las mismas consultas. Cuando el chat traia su propia copia, la del panel
   ya se habia corregido y la del chat no: el mismo tenant daba 354 cuentas de
   almacenamiento expuestas en un sitio y 112 en el otro.

2. **El contexto viaja acotado y lo dice.** Las listas completas del tenant no
   caben en un prompt sin degradar la respuesta; lo que no cabe tiene que
   declararse, porque una lista truncada en silencio se convierte en una
   afirmacion falsa del agente.

No se llama a Azure ni a Gemini: el agente se instancia sin conectar y las
consultas se interceptan. Ejecutar con:

    ./.venv/bin/python3 tests/test_contexto_agente.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

from app.agents.azure_agent import AzureInventoryAgent  # noqa: E402
from app.services import kql  # noqa: E402
from app.services.secops_service import SecOpsService  # noqa: E402


def _agente_sin_azure() -> AzureInventoryAgent:
    """Un agente que no se conecta a nada; solo se prueban sus reglas."""
    agente = AzureInventoryAgent.__new__(AzureInventoryAgent)
    agente.azure_connected = False
    agente.rg_client = None
    agente._cache = {}
    agente._cache_ttl = 900
    agente._secops = None
    agente._finops = None
    agente._cost = None
    agente._risk = None
    import threading

    agente._lock = threading.Lock()
    return agente


# ---------------------------------------------------------------------------
# Una sola definicion por regla
# ---------------------------------------------------------------------------

def test_secops_usa_el_catalogo_compartido():
    assert SecOpsService.KQL_STORAGE is kql.STORAGE_BLOBS_PUBLICOS
    assert SecOpsService.KQL_KEYVAULT is kql.KEYVAULT_PUBLICO
    assert SecOpsService.KQL_NSG is kql.NSG_ADMIN_EXPUESTO


def test_la_consulta_de_storage_no_reporta_el_inventario_entero():
    """
    La condicion que causaba el 96% de falsos positivos era incluir
    `isnull(publicNetworkAccess)`, un campo que viene nulo por defecto.
    """
    assert "properties.allowBlobPublicAccess == true" in kql.STORAGE_BLOBS_PUBLICOS
    assert "isnull(properties.publicNetworkAccess)" not in kql.STORAGE_BLOBS_PUBLICOS


def test_la_consulta_de_keyvault_filtra():
    assert "where" in kql.KEYVAULT_PUBLICO
    assert "publicNetworkAccess" in kql.KEYVAULT_PUBLICO


def test_el_agente_de_secops_lee_del_servicio():
    """El contexto de SecOps debe salir de SecOpsService, no de consultas propias."""
    agente = _agente_sin_azure()

    class ServicioFalso:
        llamado = False

        def build_report(self, subs):
            ServicioFalso.llamado = True
            return {
                "findings": [{"titulo": "x", "severidad": "critica", "tipo": "storage"}],
                "severity_summary": {"critica": 1, "alta": 0, "media": 0},
                "public_storage_accounts": [{"name": "sa1"}],
                "public_ips_active": [{"name": "ip1"}],
            }

    agente.attach_services(secops=ServicioFalso())
    contexto = agente._contexto_de_dominio("secops", ["sub"])

    assert ServicioFalso.llamado, "el agente no consulto al servicio de SecOps"
    assert contexto["security_findings"][0]["severidad"] == "critica"
    assert contexto["severity_summary"]["critica"] == 1
    assert contexto["public_ips_active_list"] == [{"name": "ip1"}]
    # Las listas por tipo no viajan: duplicaban lo que ya esta en 'findings'.
    assert "public_storage_list" not in contexto


def test_con_servicio_de_riesgo_los_hallazgos_llegan_valorados():
    """
    El chat debe priorizar igual que el panel: cuando la sintesis esta
    disponible, el contexto trae el gasto expuesto ademas de la severidad.
    """
    agente = _agente_sin_azure()

    class RiesgoFalso:
        def build_report(self, subs):
            return {
                "findings": [{
                    "titulo": "Blobs públicos", "severidad": "critica", "tipo": "storage",
                    "monthly_cost_usd": 2000.0, "cost_basis": "actual",
                }],
                "severity_summary": {"critica": 1, "alta": 0, "media": 0},
                "exposure_by_severity": {"critica": {"resources": 1, "monthly_usd": 2000.0}},
                "top_exposure": [{"name": "storage-caro", "monthly_cost_usd": 2000.0}],
                "totals": {"monthly_usd_at_risk": 2000.0},
                "coverage": {"covered_count": 1, "uncovered_count": 0, "message": "ok"},
            }

    agente.attach_services(risk=RiesgoFalso())
    contexto = agente._contexto_de_dominio("secops", ["sub"])

    assert contexto["security_findings"][0]["monthly_cost_usd"] == 2000.0
    assert contexto["cost_exposure"]["totals"]["monthly_usd_at_risk"] == 2000.0
    assert contexto["cost_exposure"]["coverage"]["covered_count"] == 1


def test_sin_servicio_de_riesgo_el_contexto_no_habla_de_dinero():
    """La sintesis es opcional: sin ella el contexto no debe fabricar un bloque vacio."""
    agente = _agente_sin_azure()

    class SecOpsFalso:
        def build_report(self, subs):
            return {"findings": [], "severity_summary": {}, "public_ips_active": []}

    agente.attach_services(secops=SecOpsFalso())
    contexto = agente._contexto_de_dominio("secops", ["sub"])
    assert "cost_exposure" not in contexto


def test_el_agente_de_finops_usa_las_consultas_del_catalogo():
    agente = _agente_sin_azure()
    ejecutadas = []

    def consulta_falsa(consulta, bypass_cache=False, subscriptions=None):
        ejecutadas.append(consulta)
        return []

    agente.query_azure_resource_graph = consulta_falsa
    agente._contexto_de_dominio("finops", ["sub"])

    assert kql.DISCOS_HUERFANOS in ejecutadas
    assert kql.IPS_SIN_ASOCIAR in ejecutadas
    assert kql.APP_PLANS_VACIOS in ejecutadas


def test_una_consulta_lenta_no_vacia_las_demas():
    """
    Antes, una sola expiracion mandaba todas las listas a vacio y el agente
    respondia como si el tenant no tuviera nada.
    """
    agente = _agente_sin_azure()
    agente.PRESUPUESTO_CONTEXTO_SEGUNDOS = 0.5

    def consulta_falsa(consulta, bypass_cache=False, subscriptions=None):
        if consulta is kql.NICS_HUERFANAS:
            import time

            time.sleep(3)
        return [{"name": "recurso"}]

    agente.query_azure_resource_graph = consulta_falsa
    contexto = agente._contexto_de_dominio("finops", ["sub"])

    assert contexto["unattached_disks_list"] == [{"name": "recurso"}]
    assert contexto["orphaned_nics_list"] == []
    assert "orphaned_nics_list" in contexto.get("consultas_incompletas", [])


# ---------------------------------------------------------------------------
# Presupuesto de contexto
# ---------------------------------------------------------------------------

def test_las_listas_cortas_viajan_tal_cual():
    agente = _agente_sin_azure()
    corta = [{"name": f"r{i}"} for i in range(5)]
    assert agente._acotar(corta, 15) == corta


def test_las_listas_largas_declaran_el_total():
    agente = _agente_sin_azure()
    larga = [{"name": f"r{i}"} for i in range(212)]
    acotada = agente._acotar(larga, 15)

    assert acotada["truncado"] is True
    assert acotada["total"] == 212, "el total tiene que seguir siendo exacto"
    assert len(acotada["muestra"]) == 15


def test_los_grupos_citados_en_la_pregunta_sobreviven_al_recorte():
    """
    Los grupos de recursos sirven para que el agente reconozca el nombre que
    escribio el usuario: el que se menciona no puede quedarse fuera del recorte.
    """
    agente = _agente_sin_azure()
    grupos = [f"rg-relleno-{i}" for i in range(300)] + ["rg-produccion-critico"]
    contexto = agente._acotar_contexto(
        {"all_resource_groups": grupos},
        "cuanto cuesta rg-produccion-critico este mes?",
    )
    acotado = contexto["all_resource_groups"]

    assert acotado["truncado"] is True
    assert acotado["total"] == 301
    assert "rg-produccion-critico" in acotado["muestra"]


def test_el_contexto_acotado_es_mucho_mas_pequeno():
    agente = _agente_sin_azure()
    contexto = {
        "connection_mode": "Azure Live Cloud Connection",
        "public_ips_active_list": [
            {"id": f"/subscriptions/x/resourceGroups/rg/providers/ip{i}", "name": f"ip{i}",
             "resourceGroup": "rg", "location": "eastus2", "sku": "Standard"}
            for i in range(400)
        ],
        "target_resource_group_resources": [
            {"name": f"r{i}", "type": "microsoft.web/sites", "properties": {"a": "b" * 200}}
            for i in range(500)
        ],
    }
    antes = len(json.dumps(contexto, indent=2, ensure_ascii=False))
    despues = len(
        json.dumps(
            agente._acotar_contexto(contexto, "hola"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

    assert despues < antes / 10, f"antes={antes} despues={despues}"


def test_un_recurso_sin_tags_no_tumba_la_respuesta():
    """
    Regresion: `search_resources` serializa los tags con `json.dumps`, asi que un
    recurso sin etiquetar viaja como la cadena "null" y `json.loads` la devuelve
    como None, no como diccionario. El codigo llamaba `.items()` sobre ese None
    dentro del try general de `ask()`, que lo tomaba por un fallo del modelo y
    respondia con el motor de reglas. Bastaba un recurso sin tags en la muestra
    —lo habitual— para que el agente dejara de usar IA sin avisar.
    """
    normalizar = AzureInventoryAgent._tags_como_dict
    assert normalizar("null") == {}
    assert normalizar(None) == {}
    assert normalizar("no es json") == {}
    assert normalizar("[1,2,3]") == {}, "una lista tampoco es un mapa de tags"
    assert normalizar('{"Environment":"Dev"}') == {"Environment": "Dev"}
    assert normalizar({"Environment": "Dev"}) == {"Environment": "Dev"}


def main() -> int:
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  PASA  {prueba.__name__}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
    print()
    print(f"{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

"""
AzureProvider sobre respuestas grabadas: lo que es propio de Azure y el contrato
general no puede saber (grabaciones/azure/).
"""

from decimal import Decimal

import pytest

from .proveedores import SUB_A1, SUB_A2, FabricaAzure

A1, A2 = f"azure:sub/{SUB_A1}", f"azure:sub/{SUB_A2}"
KV = f"azure:/subscriptions/{SUB_A1}/resourcegroups/rg-lab/providers/microsoft.keyvault/vaults/kv-lab"
NSG = f"azure:/subscriptions/{SUB_A1}/resourcegroups/rg-lab/providers/microsoft.network/networksecuritygroups/nsg-lab"
DISCO = f"azure:/subscriptions/{SUB_A1}/resourcegroups/rg-lab/providers/microsoft.compute/disks/disk-lab"


@pytest.fixture
def azure(monkeypatch, tmp_path):
    return FabricaAzure(monkeypatch, tmp_path)


def test_cuentas_desde_resource_graph(azure):
    cuentas = azure.normal().cuentas()
    assert [(c.uid, c.name) for c in cuentas] == [(A1, "Laboratorio (contrato)"), (A2, "Sin costos (contrato)")]


def test_recursos_normalizados(azure):
    recursos = {r.uid: r for r in azure.normal().recursos([A1, A2])}
    kv = recursos[KV]
    assert (kv.canonical_type, kv.region, kv.group_name, kv.account_uid) == ("secrets.vault", "eastus2", "rg-lab", A1)
    assert kv.native_id.startswith("/subscriptions/") and kv.tags == {"Environment": "prod", "Owner": "plataforma"}
    # Una tag nula no llega como "None" y un recurso sin tags tiene un diccionario vacío.
    assert recursos[DISCO].tags == {"Owner": "datos"}
    widget = next(r for r in recursos.values() if r.name == "w1")
    assert widget.canonical_type is None and widget.tags == {}


def test_cada_regla_abierta_de_un_nsg_es_un_hallazgo(azure):
    hallazgos = azure.normal().evaluar_reglas([A1, A2]).hallazgos
    nsg = sorted(h.resource_uid for h in hallazgos if h.rule_id == "network.admin-port-open")
    assert nsg == [f"{NSG}/securityrules/allow-rdp", f"{NSG}/securityrules/allow-ssh"]
    # Asociado y con IPs públicas activas: alcanzable desde internet.
    assert {h.severity for h in hallazgos if h.rule_id == "network.admin-port-open"} == {"critica"}
    kv = next(h for h in hallazgos if h.rule_id == "secrets.vault-public-network")
    assert kv.resource_uid == KV and kv.severity == "alta" and kv.details["sinFirewall"] is False


def test_costos_sumados_paginados_y_con_permisos(azure):
    p = azure.normal()
    r = p.costos_diarios([A1, A2], 7)
    filas = {(f.resource_uid, f.service_name, f.charge_date.isoformat()): f.billed_cost for f in r.filas}
    # El mismo recurso con distinta capitalización es una sola fila.
    assert filas[(KV, "Key Vault", "2026-10-07")] == Decimal("2.00")
    # La segunda página (nextLink) también llega.
    assert filas[(DISCO, "Storage", "2026-10-08")] == Decimal("3.4")
    assert filas[("", "Support", "2026-10-07")] == Decimal("0.1")
    # 403 de Cost Management: denegada, no "gasto cero".
    assert r.cobertura.denegadas == [A2] and r.cobertura.cubiertas == [A1]
    assert azure.costos.llamadas.count(SUB_A1) == 2


def test_un_error_transitorio_de_costos_se_reintenta(azure):
    r = azure.costos_con_falla_transitoria().costos_diarios([A1, A2], 7)
    assert r.cobertura.cubiertas == [A1] and r.cobertura.recuperadas == 1
    assert r.cobertura.fallidas == []


def test_creaciones_solo_de_personas(azure):
    a = azure.normal().creaciones([A1, A2])
    # El service principal (GUID) es automatización, no una creación manual.
    assert [(c.resource_uid, c.actor) for c in a.creaciones] == [(DISCO, "ana@contoso.example")]


def test_indice_de_terraform_por_uid(azure):
    assert azure.normal().recursos_gestionados() == frozenset({KV})


def test_una_consulta_nueva_sin_grabar_falla(azure):
    p = azure.normal()
    with pytest.raises(AssertionError, match="sin grabar"):
        p._inventory.azure.query_azure_resource_graph("resources | where type =~ 'nuevo'")

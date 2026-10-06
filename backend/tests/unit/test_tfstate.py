"""
Pruebas del indice de estados de Terraform.

Es la primera fuente de la plataforma que **demuestra** que un recurso esta
gestionado por IaC, en vez de deducirlo de las tags. Lo delicado no es leerlo,
sino lo que no debe hacer: un archivo de estado contiene los atributos completos
de cada recurso, y ahi viajan cadenas de conexion y llaves de acceso. De cada
estado solo pueden salir el `id` y el `type`.

La segunda regla es de direccion: el estado **exonera pero no acusa**. Que un
recurso aparezca en el estado prueba que esta gestionado; que no aparezca no
prueba nada, porque su equipo puede guardar el estado en otra cuenta.

Ejecutar con:

    ./.venv/bin/python3 tests/test_tfstate.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

from app.services import governance  # noqa: E402
from app.services.inventory_service import InventoryService  # noqa: E402
from app.services.tfstate_service import TfStateService  # noqa: E402

SUB = "11111111-1111-1111-1111-111111111111"
ID_GESTIONADO = f"/subscriptions/{SUB}/resourcegroups/rg/providers/microsoft.storage/storageaccounts/stgestionado"

ESTADO = {
    "version": 4,
    "serial": 12,
    "resources": [
        {
            "mode": "managed",
            "type": "azurerm_storage_account",
            "name": "principal",
            "instances": [{
                "attributes": {
                    "id": ID_GESTIONADO,
                    "name": "stgestionado",
                    # Un estado real trae secretos aqui. Nada de esto puede
                    # salir del modulo.
                    "primary_access_key": "SECRETO-QUE-NO-DEBE-SALIR",
                    "primary_connection_string": "DefaultEndpointsProtocol=https;AccountKey=SECRETO2",
                }
            }],
        },
        {
            # Los objetos de Entra ID no estan en el inventario de Azure.
            "mode": "managed",
            "type": "azuread_application",
            "name": "app",
            "instances": [{"attributes": {"id": "00000000-aaaa-bbbb-cccc-000000000000"}}],
        },
        {
            "mode": "data",
            "type": "azurerm_client_config",
            "name": "actual",
            "instances": [{"attributes": {"id": "no-gestionado"}}],
        },
    ],
}


def test_solo_se_extraen_ids_y_tipos():
    """El resto del estado se descarta: ahi viven los secretos."""
    datos = TfStateService._extraer(json.dumps(ESTADO).encode("utf-8"))
    serializado = json.dumps({"ids": sorted(datos["ids"]), "tipos": datos["tipos"]})
    assert "SECRETO-QUE-NO-DEBE-SALIR" not in serializado
    assert "SECRETO2" not in serializado
    assert datos["tipos"] == {"azurerm_storage_account": 1}


def test_solo_cuentan_los_recursos_gestionados_de_azure():
    """Un `data source` no lo gestiona nadie, y un objeto de Entra ID no está en el inventario."""
    datos = TfStateService._extraer(json.dumps(ESTADO).encode("utf-8"))
    assert datos["ids"] == {ID_GESTIONADO}


def test_un_estado_ilegible_no_rompe_el_indice():
    datos = TfStateService._extraer(b'{"resources": [')
    assert datos["ok"] is False
    assert datos["ids"] == set()


def test_el_estado_exonera_del_shadow_it():
    """
    Un recurso sin tags, sin custodio y sin marca de IaC seria candidato; si
    aparece en el estado, esta gestionado y deja de serlo.
    """
    evaluacion = InventoryService.evaluate_mandatory_tags({})
    sin_estado = InventoryService.classify_shadow_it(
        {}, None, evaluacion, "rg", "microsoft.storage/storageaccounts",
        ID_GESTIONADO, set()
    )
    con_estado = InventoryService.classify_shadow_it(
        {}, None, evaluacion, "rg", "microsoft.storage/storageaccounts",
        ID_GESTIONADO, {ID_GESTIONADO}
    )
    assert sin_estado["isShadowItCandidate"] is True
    assert con_estado["isShadowItCandidate"] is False
    assert con_estado["iacEvidenceSource"] == "estado"


def test_la_evidencia_por_tags_se_distingue_de_la_probada():
    evaluacion = InventoryService.evaluate_mandatory_tags({"provisioning_method": "terraform"})
    r = InventoryService.classify_shadow_it(
        {"provisioning_method": "terraform"}, None, evaluacion,
        "rg", "microsoft.storage/storageaccounts", ID_GESTIONADO, set()
    )
    assert r["hasIacEvidence"] is True
    assert r["iacEvidenceSource"] == "tags"


def test_no_aparecer_en_el_estado_no_acusa_por_si_solo():
    """
    Un recurso bien etiquetado y con custodio no se convierte en candidato solo
    porque su estado viva en otra cuenta.
    """
    tags = {"Customer": "Acme", "Tenant": "AcmeGroup", "Platform": "CorePlatform",
            "Product": "DevOps", "Suite": "Shared", "Environment": "Dev"}
    evaluacion = InventoryService.evaluate_mandatory_tags(tags)
    r = InventoryService.classify_shadow_it(
        tags, None, evaluacion, "rg", "microsoft.storage/storageaccounts",
        "/subscriptions/x/otro", set()
    )
    assert r["isShadowItCandidate"] is False


def test_la_consulta_kql_lleva_los_ids_del_estado():
    expr = governance.kql_gestionado_por_terraform({ID_GESTIONADO})
    assert ID_GESTIONADO in expr
    assert expr.startswith("(tolower(id) in (")


def test_sin_estados_la_consulta_no_afirma_nada():
    """Sin indice, la expresión es falsa y manda la regla de tags."""
    assert governance.kql_gestionado_por_terraform(set()) == "false"


def test_demasiados_ids_no_generan_una_consulta_impracticable():
    muchos = {f"/subscriptions/x/r{i}" for i in range(governance.MAX_IDS_EN_CONSULTA + 1)}
    assert governance.kql_gestionado_por_terraform(muchos) == "false"

def test_varias_cuentas_de_estado_se_suman_y_una_caida_no_invalida_las_demas():
    """Cada proyecto suele guardar su estado en su propia cuenta."""
    from app.services import tfstate_service as modulo

    class Credencial:
        def get_token(self, scope):
            return type("T", (), {"token": "x"})()

    class Agente:
        azure_credentials = Credencial()

    listado = (
        '<?xml version="1.0"?><EnumerationResults><Blobs>'
        '<Blob><Name>proyecto.tfstate</Name></Blob></Blobs><NextMarker/></EnumerationResults>'
    )
    estado = json.dumps({"resources": [{"mode": "managed", "type": "azurerm_resource_group", "instances": [
        {"attributes": {"id": "/subscriptions/s/resourceGroups/rg-a"}}]}]}).encode()

    class Respuesta:
        def __init__(self, codigo, texto="", contenido=b""):
            self.status_code, self.text, self.content = codigo, texto, contenido

    def get_falso(url, headers=None, timeout=None):
        if url.startswith("https://caida."):
            return Respuesta(403)
        if "comp=list" in url:
            return Respuesta(200, texto=listado)
        return Respuesta(200, contenido=estado)

    originales = (modulo.SOURCES, modulo.ENABLED, modulo.requests.get)
    try:
        modulo.SOURCES = [("cuentaa", "tfstate"), ("caida", "tfstate")]
        modulo.ENABLED = True
        modulo.requests.get = get_falso
        indice = TfStateService(Agente()).get_index(force=True)
    finally:
        modulo.SOURCES, modulo.ENABLED, modulo.requests.get = originales

    assert indice["available"]
    assert indice["managed_ids"] == {"/subscriptions/s/resourcegroups/rg-a"}
    assert [e["name"] for e in indice["states"]] == ["cuentaa/tfstate/proyecto.tfstate"]
    assert len(indice["sources_failed"]) == 1 and "caida" in indice["sources_failed"][0]

def test_solo_los_recursos_de_primer_nivel_pueden_ser_cobertura_u_obsoletos():
    """Subrecursos y role assignments del estado no estan en `resources`."""
    base = "/subscriptions/s/resourcegroups/rg/providers"
    assert governance.es_recurso_inventariable(f"{base}/microsoft.storage/storageaccounts/st1")
    assert not governance.es_recurso_inventariable(
        f"{base}/microsoft.storage/storageaccounts/st1/blobservices/default/containers/c1")
    assert not governance.es_recurso_inventariable(
        f"{base}/microsoft.insights/components/ai/providers/microsoft.authorization/roleassignments/x")
    assert not governance.es_recurso_inventariable("/subscriptions/s/resourcegroups/rg")
    assert not governance.es_recurso_inventariable(
        "/subscriptions/s/providers/microsoft.consumption/budgets/b")


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  PASA  {prueba.__name__}")
        except AssertionError as exc:
            fallos += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  ERROR {prueba.__name__}: {type(exc).__name__}: {exc}")

    print()
    print(f"{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    sys.exit(1 if fallos else 0)

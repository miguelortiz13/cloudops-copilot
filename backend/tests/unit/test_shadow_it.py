"""
Pruebas de la regla de Shadow IT.

La regla anterior marcaba como candidato todo recurso sin tag de IaC que ademas
no fuera conforme **o** no tuviera `managedBy`. Medido contra produccion eso
senalaba 545 de 602 recursos (90.5%), y 499 de ellos tenian las seis tags
obligatorias completas: los marcaba solo por no tener `managedBy`, un campo que
Azure rellena unicamente en recursos hijos —el 2.5% del tenant— y que nada dice
sobre como se aprovisiono nada.

Lo que se fija aqui es que hacen falta cuatro ausencias para acusar a un recurso,
y que ninguna de ellas por separado basta.

Ejecutar con:

    ./.venv/bin/python3 tests/test_shadow_it.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.inventory_service import InventoryService  # noqa: E402

SIN_TAGS = {}
TAGS_COMPLETAS = {
    "Customer": "Acme", "Tenant": "AcmeGroup", "Platform": "CorePlatform",
    "Product": "DevOps", "Suite": "Shared", "Environment": "Dev",
}


def clasificar(tags, managed_by=None, rg="rg-app", tipo="microsoft.storage/storageaccounts"):
    evaluacion = InventoryService.evaluate_mandatory_tags(tags)
    return InventoryService.classify_shadow_it(tags, managed_by, evaluacion, rg, tipo)


def test_sin_tags_sin_duenio_y_sin_iac_es_candidato():
    """El caso real: una VNet creada por el asistente del portal."""
    r = clasificar(SIN_TAGS, rg="rg_dev_paas", tipo="microsoft.network/virtualnetworks")
    assert r["isShadowItCandidate"] is True
    assert "IaC" in r["shadowItReason"]


def test_las_tags_obligatorias_completas_bastan_para_no_acusar():
    """
    499 recursos de produccion caian aqui: perfectamente etiquetados y marcados
    como Shadow IT solo porque Azure no les puso `managedBy`.
    """
    r = clasificar(TAGS_COMPLETAS)
    assert r["isShadowItCandidate"] is False


def test_un_custodio_basta_aunque_falten_tags_obligatorias():
    r = clasificar({"OwnerTech": "plataforma@example.com"})
    assert r["isShadowItCandidate"] is False


def test_la_evidencia_de_iac_basta_aunque_no_haya_nada_mas():
    r = clasificar({"provisioning_method": "terraform"})
    assert r["isShadowItCandidate"] is False
    assert r["hasIacEvidence"] is True


def test_un_valor_terraform_en_cualquier_clave_cuenta_como_iac():
    r = clasificar({"Origen": "Terraform"})
    assert r["hasIacEvidence"] is True
    assert r["isShadowItCandidate"] is False


def test_los_recursos_derivados_quedan_fuera():
    """Los nodos de AKS y lo que gobierna otro recurso no son deuda del equipo."""
    por_managed_by = clasificar(SIN_TAGS, managed_by="/subscriptions/x/providers/vmss")
    por_grupo_de_nodos = clasificar(SIN_TAGS, rg="MC_rg-aks_aks-dev_eastus2")
    por_tipo = clasificar(SIN_TAGS, tipo="microsoft.alertsmanagement/smartdetectoralertrules")
    for r in (por_managed_by, por_grupo_de_nodos, por_tipo):
        assert r["isDerived"] is True
        assert r["isShadowItCandidate"] is False


def test_la_ausencia_de_managed_by_ya_no_acusa_por_si_sola():
    """Era la condicion que inflaba la metrica al 90% del inventario."""
    r = clasificar(TAGS_COMPLETAS, managed_by=None)
    assert r["isShadowItCandidate"] is False


def test_un_valor_invalido_no_cuenta_como_custodio():
    """'Por confirmar' en la tag Owner no identifica a nadie."""
    r = clasificar({"Owner": "Por confirmar"})
    assert r["isShadowItCandidate"] is True


def test_el_motivo_dice_cuantas_tags_faltan():
    r = clasificar({"Customer": "Acme"})
    assert "faltan 5 de 6" in r["shadowItReason"], r["shadowItReason"]


def test_el_custodio_reconoce_las_claves_que_usa_la_organizacion():
    """
    Con las seis claves originales solo 5 de 602 recursos del tenant tenian
    custodio; el tenant etiqueta con OwnerTech, OwnerFunc y Author.
    """
    for clave in ["OwnerTech", "OwnerFunc", "Author", "Team", "Custodio"]:
        evaluacion = InventoryService.evaluate_mandatory_tags({clave: "alguien"})
        gob = InventoryService.build_governance_info(
            {clave: "alguien"}, None, evaluacion,
            clasificar({clave: "alguien"}),
        )
        assert gob["hasOwnerCandidate"] is True, clave


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

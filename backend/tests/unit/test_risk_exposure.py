"""
Pruebas de la sintesis entre SecOps y FinOps.

Los dos modulos no se conocian: el panel de seguridad ordenaba por severidad y
ahi terminaba, de modo que una cuenta de almacenamiento publica de 2.000 USD al
mes y una de 3 USD se veian igual de urgentes.

Lo que se fija aqui es como se combinan las dos senales y, sobre todo, que no se
inventen ceros: un recurso sin factura vale *desconocido*, no cero, y el costo de
una regla de NSG no es atribuible al hallazgo.

Ejecutar con:

    ./.venv/bin/python3 tests/test_risk_exposure.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services.risk_service import RiskService  # noqa: E402

SUB_MEDIDA = "11111111-1111-1111-1111-111111111111"
SUB_SIN_COSTO = "22222222-2222-2222-2222-222222222222"


def rid(sub, nombre, tipo="microsoft.storage/storageaccounts"):
    return f"/subscriptions/{sub}/resourcegroups/rg/providers/{tipo}/{nombre}"


STORAGE_CARO = rid(SUB_MEDIDA, "storage-caro")
STORAGE_BARATO = rid(SUB_MEDIDA, "storage-barato")
STORAGE_SIN_MEDIR = rid(SUB_SIN_COSTO, "storage-sin-medir")
NSG = rid(SUB_MEDIDA, "nsg-abierto", "microsoft.network/networksecuritygroups")
STORAGE_GRATIS = rid(SUB_MEDIDA, "storage-sin-cargo")


class SecOpsFalso:
    """Devuelve hallazgos fijos, con la forma que produce SecOpsService."""

    def build_report(self, subs):
        return {
            "findings": [
                {"id": STORAGE_BARATO, "name": "storage-barato", "tipo": "storage",
                 "severidad": "critica", "titulo": "Blobs públicos"},
                {"id": STORAGE_CARO, "name": "storage-caro", "tipo": "storage",
                 "severidad": "critica", "titulo": "Blobs públicos"},
                # El mismo storage caro, senalado por una segunda regla.
                {"id": STORAGE_CARO, "name": "storage-caro", "tipo": "storage",
                 "severidad": "alta", "titulo": "Sin firewall de red"},
                {"id": STORAGE_SIN_MEDIR, "name": "storage-sin-medir", "tipo": "storage",
                 "severidad": "critica", "titulo": "Blobs públicos"},
                {"id": NSG, "name": "nsg-abierto", "tipo": "nsg",
                 "severidad": "critica", "titulo": "Puerto de administración abierto"},
                {"id": STORAGE_GRATIS, "name": "storage-sin-cargo", "tipo": "storage",
                 "severidad": "critica", "titulo": "Blobs públicos"},
            ],
            "severity_summary": {"critica": 4, "alta": 1, "media": 0},
        }


class CostFalso:
    def costs_for(self, subs, allow_query=True):
        return {
            "status": "partial",
            "currency": "USD",
            "window_days": 30,
            "costs": {STORAGE_CARO.lower(): 2000.0, STORAGE_BARATO.lower(): 3.0,
                      STORAGE_GRATIS.lower(): 0.0},
            "coverage": {"covered": [SUB_MEDIDA], "denied": [SUB_SIN_COSTO], "failed": []},
            "source": "cache",
            "cache_age_seconds": 0,
        }


def reporte():
    return RiskService(SecOpsFalso(), CostFalso()).build_report([SUB_MEDIDA, SUB_SIN_COSTO])


def test_el_dinero_desempata_dentro_de_la_misma_severidad():
    """El caso que motivo todo: 2.000 USD al mes antes que 3 USD."""
    criticos = [h for h in reporte()["findings"] if h["severidad"] == "critica"]
    assert criticos[0]["name"] == "storage-caro", [h["name"] for h in criticos]


def test_lo_que_no_se_puede_valorar_no_cae_al_fondo():
    """
    Una regla de NSG abierta a internet no es menos urgente que un Key Vault
    facturado en cero solo porque no sepamos ponerle precio. Tratar
    "desconocido" como cero es el error que este modulo evita.
    """
    nombres = [h["name"] for h in reporte()["findings"] if h["severidad"] == "critica"]
    assert nombres.index("nsg-abierto") < nombres.index("storage-sin-cargo"), nombres


def test_lo_medido_en_cero_va_al_final_de_su_severidad():
    """De ese si consta que no cuesta nada, que es informacion, no ausencia."""
    criticos = [h["name"] for h in reporte()["findings"] if h["severidad"] == "critica"]
    assert criticos[-1] == "storage-sin-cargo", criticos


def test_la_severidad_manda_sobre_el_dinero():
    """Un critico barato sigue por delante de un alto caro."""
    orden = [(h["severidad"], h["name"]) for h in reporte()["findings"]]
    assert orden.index(("critica", "storage-barato")) < orden.index(("alta", "storage-caro"))


def test_un_recurso_sin_factura_no_vale_cero():
    hallazgo = next(h for h in reporte()["findings"] if h["name"] == "storage-sin-medir")
    assert hallazgo["cost_basis"] == "unavailable"
    resumen = reporte()["exposure_by_severity"]["critica"]
    assert resumen["unmeasured"] == 1
    # Y no engorda el total con un cero que se leeria como "no importa".
    # Medidos: el caro, el barato y el que factura cero.
    assert resumen["measured"] == 3


def test_el_costo_de_una_regla_de_nsg_no_se_atribuye_al_hallazgo():
    """Una NSG no factura; lo que vale dinero son las maquinas de detras."""
    hallazgo = next(h for h in reporte()["findings"] if h["tipo"] == "nsg")
    assert hallazgo["cost_basis"] == "not_applicable"
    # Tampoco entra en el conteo de recursos afectados con valor.
    assert all(e["tipo"] != "nsg" for e in reporte()["top_exposure"])


def test_un_recurso_con_dos_hallazgos_cuenta_su_gasto_una_vez():
    rep = reporte()
    assert rep["totals"]["monthly_usd_at_risk"] == 2003.0, rep["totals"]
    caro = next(e for e in rep["top_exposure"] if e["name"] == "storage-caro")
    assert caro["hallazgos"] == 2
    # Se queda con la severidad mas alta de las dos.
    assert caro["severidad"] == "critica"


def test_los_totales_distinguen_medido_de_desconocido():
    t = reporte()["totals"]
    assert t["affected_resources"] == 4
    assert t["measured_resources"] == 3
    assert t["unmeasured_resources"] == 1


def test_la_cobertura_se_declara_en_el_mensaje():
    cobertura = reporte()["coverage"]
    assert cobertura["covered_count"] == 1
    assert cobertura["uncovered_count"] == 1
    assert "1 de 2 suscripciones" in cobertura["message"], cobertura["message"]
    assert "desconocido" in cobertura["message"]


def test_sin_datos_de_costo_el_orden_sigue_siendo_por_severidad():
    class SinCosto:
        def costs_for(self, subs, allow_query=True):
            return {"status": "unauthorized", "currency": "USD", "window_days": 30,
                    "costs": {}, "coverage": {"covered": [], "denied": list(subs), "failed": []}}

    rep = RiskService(SecOpsFalso(), SinCosto()).build_report([SUB_MEDIDA])
    severidades = [h["severidad"] for h in rep["findings"]]
    assert severidades == sorted(severidades, key=lambda s: {"critica": 0, "alta": 1}[s])
    assert rep["totals"]["monthly_usd_at_risk"] == 0.0
    assert "solo por severidad" in rep["coverage"]["message"]


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

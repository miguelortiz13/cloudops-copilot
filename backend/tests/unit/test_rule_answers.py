"""
Pruebas del motor de reglas de los agentes de costos y seguridad.

Sin Gemini, el agente de costos respondia con las reglas de inventario ("no
logre interpretar tu pregunta"). Se fija que cada agente conteste con los datos
de su propio servicio.

Ejecutar con:

    ./.venv/bin/python3 tests/unit/test_rule_answers.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import conftest  # noqa: E402,F401  (aisla las pruebas del .env local)

from app.agents import rule_answers  # noqa: E402

SUB = "11111111-1111-1111-1111-111111111111"
ST = f"/subscriptions/{SUB}/resourcegroups/rg/providers/microsoft.storage/storageaccounts/st1"


class Costos:
    def costs_for(self, subs, allow_query=True):
        return {"currency": "USD", "window_days": 30, "costs": {ST: 12.0},
                "coverage": {"covered": [SUB], "denied": [], "failed": []}}

    def get_daily_costs(self, subs, days=30, pace_seconds=0.0, force=False):
        return {"series": {}, "coverage": {"covered": [SUB], "denied": [], "failed": []}}


class FinOps:
    def build_report(self, subs):
        return {"savings_lifecycle": {"potential_savings_usd": 4.0},
                "unattached_disks": [{"name": "disco-viejo", "monthly_cost_usd": 4.0}],
                "cost_data": {"currency": "USD"}}


class Riesgo:
    def build_report(self, subs):
        return {"findings": [
            {"severidad": "critica", "titulo": "Key Vault público", "name": "kv1", "recomendacion": "Private endpoint."},
            {"severidad": "alta", "titulo": "Sin HTTPS", "name": "app1"},
        ]}


class Agente:
    _finops = FinOps()
    _risk = Riesgo()

    def _get_cost(self):
        return Costos()

    def query_azure_resource_graph(self, kql, bypass_cache=False, subscriptions=None):
        if "resourcecontainers" in kql:
            return [{"subscriptionId": SUB, "name": "Lab"}]
        return [{"id": ST, "name": "st1", "type": "microsoft.storage/storageaccounts",
                 "resourceGroup": "rg", "location": "eastus2", "subscriptionId": SUB, "tags": {}}]


def test_costos_responde_con_el_gasto_real():
    r = rule_answers.respuesta_finops(Agente(), "¿En qué se va el gasto?", None)
    assert "12.00 USD" in r["answer"]
    assert "Storage" in r["answer"]
    assert r["mode"] == "azure_live_rules_finops"


def test_costos_responde_ahorro_cuando_se_pregunta_por_ahorro():
    r = rule_answers.respuesta_finops(Agente(), "¿Cuáles son las oportunidades de ahorro?", None)
    assert "disco-viejo" in r["answer"]
    assert "4.00 USD" in r["answer"]


def test_seguridad_lista_lo_critico_primero():
    r = rule_answers.respuesta_secops(Agente(), None)
    assert "Críticos: **1**" in r["answer"]
    assert r["answer"].index("kv1") < r["answer"].index("app1")


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
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    sys.exit(1 if fallos else 0)

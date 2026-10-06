"""
Pruebas de la segunda pasada de la precarga de costos.

Cost Management responde 429 con facilidad. En el tenant de produccion, con casi
treinta suscripciones, cada ciclo de precarga dejaba unas diez sin dato: el panel
las mostraba como estimadas durante seis horas —hasta el siguiente ciclo— pese a
que el Service Principal si tiene permisos de costo sobre ellas.

La segunda pasada reconsulta solo esas suscripciones y fusiona lo que recupera
en la entrada de cache del scope completo, que es la que lee el panel. Lo
delicado es no contar dos veces: si la primera pasada devolvio datos de cache
vencida, esa respuesta ya trae el gasto de las suscripciones que ahora se
reintentan.

Ejecutar con:

    ./.venv/bin/python3 tests/test_cost_warm_retry.py
"""

import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services import cost_service as modulo  # noqa: E402
from app.services.cost_service import CostService  # noqa: E402

SUB_OK = "11111111-1111-1111-1111-111111111111"
SUB_429 = "22222222-2222-2222-2222-222222222222"
SCOPE = [SUB_OK, SUB_429]

RECURSO_OK = f"/subscriptions/{SUB_OK}/rg/a/disco"
RECURSO_429 = f"/subscriptions/{SUB_429}/rg/b/disco"


def servicio():
    """
    Servicio con un directorio de cache propio y desechable.

    La cache se persiste en disco, asi que sin aislar el directorio las pruebas
    se contaminarian entre si —y escribirian en el del proyecto.
    """
    class AgenteSinAzure:
        azure_connected = False
        azure_credentials = None

    directorio = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, directorio, True)
    return CostService(AgenteSinAzure(), cache_dir=directorio)


def primera_pasada():
    return {
        "status": "partial",
        "currency": "USD",
        "window_days": 30,
        "costs": {RECURSO_OK: 10.0},
        "coverage": {"covered": [SUB_OK], "denied": [], "failed": [SUB_429]},
    }


def reintento():
    return {
        "status": "success",
        "currency": "USD",
        "window_days": 30,
        "costs": {RECURSO_429: 25.0},
        "coverage": {"covered": [SUB_429], "denied": [], "failed": []},
    }


def test_la_suscripcion_recuperada_deja_de_estar_fallida():
    fusionado = servicio()._fusionar_por_recurso(SCOPE, primera_pasada(), reintento())
    assert fusionado["coverage"]["covered"] == [SUB_OK, SUB_429]
    assert fusionado["coverage"]["failed"] == []
    assert fusionado["status"] == "success", fusionado["status"]


def test_el_gasto_recuperado_se_suma_al_de_la_primera_pasada():
    fusionado = servicio()._fusionar_por_recurso(SCOPE, primera_pasada(), reintento())
    assert fusionado["costs"] == {RECURSO_OK: 10.0, RECURSO_429: 25.0}


def test_la_fusion_queda_en_la_cache_del_scope_completo():
    """Es la entrada que consulta el panel; una del sub-scope no le serviria."""
    svc = servicio()
    svc._fusionar_por_recurso(SCOPE, primera_pasada(), reintento())
    clave = ("by_resource", tuple(sorted(SCOPE)), modulo.DEFAULT_WINDOW_DAYS)
    guardado = svc._get_cached(clave)
    assert guardado is not None, "la fusion no se escribio en la cache del scope"
    assert guardado["costs"][RECURSO_429] == 25.0


def test_una_respuesta_de_cache_vencida_no_se_duplica():
    """
    Si la primera pasada fallo entera y se sirvio cache vencida, esa respuesta ya
    trae el gasto de la suscripcion que ahora se reintenta: volver a sumarla
    duplicaria la serie diaria.
    """
    svc = servicio()
    vencida = {
        "status": "partial", "currency": "USD",
        "series": {"2026-08-01": 100.0},
        "coverage": {"covered": [SUB_OK, SUB_429], "denied": [], "failed": []},
        "stale": True,
    }
    extra = {
        "status": "success", "currency": "USD",
        "series": {"2026-08-01": 40.0},
        "coverage": {"covered": [SUB_429], "denied": [], "failed": []},
    }
    assert svc._nuevas_cubiertas(vencida, extra) == []


def test_la_serie_diaria_suma_por_fecha_lo_recuperado():
    svc = servicio()
    base = {"status": "partial", "currency": "USD", "series": {"2026-08-01": 100.0},
            "coverage": {"covered": [SUB_OK], "denied": [], "failed": [SUB_429]}}
    extra = {"status": "success", "currency": "USD",
             "series": {"2026-08-01": 40.0, "2026-08-02": 5.0},
             "coverage": {"covered": [SUB_429], "denied": [], "failed": []}}
    fusionado = svc._fusionar_diario(SCOPE, base, extra)
    assert fusionado["series"] == {"2026-08-01": 140.0, "2026-08-02": 5.0}
    assert "stale" not in fusionado


def test_warm_reintenta_solo_las_fallidas_y_lo_reporta():
    svc = servicio()
    modulo.WARM_RETRY_BACKOFF_SECONDS = 0.0
    llamadas = []

    def falso_por_recurso(subs, days=30, pace_seconds=0.0, force=False):
        llamadas.append(list(subs))
        return primera_pasada() if len(subs) == 2 else reintento()

    def falso_diario(subs, days=30, pace_seconds=0.0, force=False):
        return {"status": "partial", "currency": "USD", "series": {},
                "coverage": {"covered": [SUB_OK], "denied": [], "failed": [SUB_429]}}

    svc.get_cost_by_resource = falso_por_recurso
    svc.get_daily_costs = falso_diario

    resultado = svc.warm(SCOPE)
    assert llamadas == [SCOPE, [SUB_429]], llamadas
    assert resultado["recovered_on_retry"] == 1, resultado
    assert resultado["covered"] == 2 and resultado["failed"] == 0, resultado


def test_el_ritmo_por_defecto_deja_respirar_a_la_api():
    """Con 2.5s se perdian diez suscripciones por ciclo; el reintento va al doble."""
    assert modulo.WARM_PACE_SECONDS >= 8.0, modulo.WARM_PACE_SECONDS
    assert modulo.WARM_RETRY_PACE_FACTOR >= 2.0


# ----------------------------------------------------------------------
# Reutilizacion de la precarga desde un scope distinto
# ----------------------------------------------------------------------
#
# La cache se indexa por el scope completo de la consulta. El chat pregunta por
# el costo de un grupo de recursos, es decir de una sola suscripcion, y esa
# clave nunca coincide con la que dejo la precarga de las treinta: lanzaba una
# consulta viva que competia con la precarga por la cuota de Cost Management,
# recibia 429 y devolvia estimaciones. Verificado en produccion: el chat decia
# "estimado 800.50" del mismo grupo que el panel mostraba facturado en 1178.32.


def cache_precargada(svc, subs=SCOPE):
    svc._set_cached(
        ("by_resource", tuple(sorted(subs)), modulo.DEFAULT_WINDOW_DAYS),
        {
            "status": "success", "currency": "USD", "window_days": 30,
            "costs": {RECURSO_OK: 10.0, RECURSO_429: 25.0},
            "coverage": {"covered": list(subs), "denied": [], "failed": []},
        },
    )


def test_una_sola_suscripcion_se_sirve_de_la_precarga_del_scope_completo():
    svc = servicio()
    cache_precargada(svc)
    svc.get_cost_by_resource = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no debe consultar a Cost Management: el dato ya estaba en cache")
    )

    datos = svc.costs_for([SUB_OK])
    assert datos["source"] == "cache", datos["source"]
    assert datos["coverage"]["covered"] == [SUB_OK]
    # Solo el gasto de la suscripcion pedida, no el de todo el scope cacheado.
    assert datos["costs"] == {RECURSO_OK: 10.0}


def test_solo_se_consulta_lo_que_ninguna_entrada_cubre():
    svc = servicio()
    cache_precargada(svc, [SUB_OK])
    consultadas = []

    def falso(subs, days=30, **kwargs):
        consultadas.append(list(subs))
        return reintento()

    svc.get_cost_by_resource = falso
    datos = svc.costs_for(SCOPE)
    assert consultadas == [[SUB_429]], consultadas
    assert datos["source"] == "mixto", datos["source"]
    assert datos["costs"] == {RECURSO_OK: 10.0, RECURSO_429: 25.0}


def test_una_entrada_vencida_sigue_siendo_facturacion_real():
    """El TTL controla cuando refrescar, no si el dato es real."""
    svc = servicio()
    cache_precargada(svc)
    with svc._lock:
        clave = ("by_resource", tuple(sorted(SCOPE)), modulo.DEFAULT_WINDOW_DAYS)
        valor = svc._cache[clave][1]
        svc._cache[clave] = (0.0, valor)  # guardada en 1970: TTL vencido de sobra

    datos = svc.costs_for([SUB_OK], allow_query=False)
    assert datos["costs"] == {RECURSO_OK: 10.0}
    assert datos["cache_age_seconds"] > modulo.DEFAULT_TTL_SECONDS


def test_sin_cache_y_sin_permiso_de_consultar_no_se_inventa_cobertura():
    datos = servicio().costs_for([SUB_OK], allow_query=False)
    assert datos["costs"] == {}
    assert datos["coverage"]["covered"] == []
    assert datos["coverage"]["failed"] == [SUB_OK]


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

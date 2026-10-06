"""
Pruebas de la cache de costos que sobrevive a los reinicios.

La cache vivia solo en memoria. Cada reinicio la vaciaba, y como la precarga
arranca con el proceso, cada despliegue volvia a gastar las ~56 llamadas de Cost
Management. Medido en produccion: cuatro despliegues en dos horas agotaron la
cuota y un ciclo que venia cubriendo 24 de 30 suscripciones bajo a 9, con lo que
el panel mostro "sin gasto facturado" durante horas.

Se persiste en el File Share que ya esta montado para el Excel y el historico de
KPIs, sin crear ningun recurso nuevo en Azure. Lo que se fija aqui es que el dato
vuelve tras el reinicio, que un archivo corrupto no impide arrancar, y que con
cache vigente la precarga se salta en vez de volver a consultar.

Ejecutar con:

    ./.venv/bin/python3 tests/test_cost_cache_persistente.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from app.services import cost_service as modulo  # noqa: E402
from app.services.cost_service import CostService  # noqa: E402

SUB = "11111111-1111-1111-1111-111111111111"
RECURSO = f"/subscriptions/{SUB}/rg/a/disco"
CLAVE = ("by_resource", (SUB,), modulo.DEFAULT_WINDOW_DAYS)

PAYLOAD = {
    "status": "success",
    "currency": "USD",
    "window_days": 30,
    "costs": {RECURSO: 42.0},
    "coverage": {"covered": [SUB], "denied": [], "failed": []},
}


class AgenteSinAzure:
    azure_connected = False
    azure_credentials = None


def servicio(directorio):
    return CostService(AgenteSinAzure(), cache_dir=directorio)


def test_el_gasto_sobrevive_al_reinicio():
    """Es el caso que motivo el cambio: reiniciar no puede costar la cobertura."""
    directorio = tempfile.mkdtemp()
    try:
        servicio(directorio)._set_cached(CLAVE, PAYLOAD)
        # Otra instancia = otro proceso, como tras un despliegue.
        recuperado = servicio(directorio)._get_cached(CLAVE)
        assert recuperado is not None, "la cache no se recupero del disco"
        assert recuperado["costs"][RECURSO] == 42.0
        assert recuperado["coverage"]["covered"] == [SUB]
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_lo_recuperado_alimenta_la_busqueda_por_suscripcion():
    """`costs_for` lee del diccionario en memoria, asi que hay que repoblarlo."""
    directorio = tempfile.mkdtemp()
    try:
        servicio(directorio)._set_cached(CLAVE, PAYLOAD)
        datos = servicio(directorio).costs_for([SUB], allow_query=False)
        assert datos["source"] == "cache"
        assert datos["costs"] == {RECURSO: 42.0}
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_una_entrada_demasiado_vieja_se_descarta():
    """Pasada la edad maxima el dato ya no sirve ni como respaldo ante un 429."""
    directorio = tempfile.mkdtemp()
    try:
        svc = servicio(directorio)
        svc._set_cached(CLAVE, PAYLOAD)
        archivo = os.path.join(directorio, svc._key_to_filename(CLAVE))
        with open(archivo, "r", encoding="utf-8") as fh:
            registro = json.load(fh)
        registro["saved_at"] = time.time() - modulo.CACHE_MAX_AGE_SECONDS - 60
        with open(archivo, "w", encoding="utf-8") as fh:
            json.dump(registro, fh)

        nuevo = servicio(directorio)
        assert nuevo._get_stale(CLAVE) is None
        assert not os.path.exists(archivo), "la entrada vencida deberia borrarse"
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_un_archivo_corrupto_no_impide_arrancar():
    """Un JSON truncado por un reinicio a media escritura no puede tumbar el arranque."""
    directorio = tempfile.mkdtemp()
    try:
        with open(os.path.join(directorio, "roto.json"), "w", encoding="utf-8") as fh:
            fh.write('{"key": [')
        svc = servicio(directorio)
        svc._set_cached(CLAVE, PAYLOAD)
        assert svc._get_cached(CLAVE) is not None
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_sin_directorio_escribible_el_servicio_sigue_funcionando():
    """La persistencia es una optimizacion, nunca un requisito."""
    svc = CostService(AgenteSinAzure(), cache_dir="/proc/no-escribible/jamas")
    svc._set_cached(CLAVE, PAYLOAD)
    assert svc._get_cached(CLAVE)["costs"][RECURSO] == 42.0


def test_con_cache_vigente_no_hay_que_precargar():
    """Lo que evita gastar las ~56 llamadas en cada despliegue."""
    directorio = tempfile.mkdtemp()
    try:
        servicio(directorio)._set_cached(CLAVE, PAYLOAD)
        frescura = servicio(directorio).cache_freshness([SUB])
        assert frescura["cached"] is True
        assert frescura["should_warm"] is False
        assert frescura["covered"] == 1
        assert frescura["remaining_seconds"] > 0
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_con_la_cache_vencida_si_hay_que_precargar():
    directorio = tempfile.mkdtemp()
    try:
        svc = servicio(directorio)
        svc._set_cached(CLAVE, PAYLOAD)
        with svc._lock:
            svc._cache[CLAVE] = (time.time() - modulo.DEFAULT_TTL_SECONDS - 10, PAYLOAD)
        frescura = svc.cache_freshness([SUB])
        assert frescura["should_warm"] is True
        assert frescura["remaining_seconds"] == 0
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_sin_nada_cacheado_se_precarga():
    directorio = tempfile.mkdtemp()
    try:
        frescura = servicio(directorio).cache_freshness([SUB])
        assert frescura["cached"] is False
        assert frescura["should_warm"] is True
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


def test_las_denegaciones_no_se_persisten():
    """
    Su TTL es de una hora y un permiso recien otorgado debe detectarse solo:
    arrastrar un 403 viejo entre reinicios lo ocultaria.
    """
    directorio = tempfile.mkdtemp()
    try:
        svc = servicio(directorio)
        svc._mark_denied(SUB)
        assert svc._is_denied(SUB) is True
        assert servicio(directorio)._is_denied(SUB) is False
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


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

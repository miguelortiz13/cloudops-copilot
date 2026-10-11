"""
Contrato de la capa de proveedores (app/providers/base.py), el mismo para todos.

Corre contra AzureProvider (servicios reales sobre respuestas grabadas) y contra
el proveedor en memoria, que es el doble de las pruebas de los recolectores: si
el doble cumple el mismo contrato que Azure, lo que prueban los recolectores con
él vale para Azure. Una nube nueva se agrega como una fábrica más en
`FABRICAS` y debe pasar esta batería sin cambios.
"""

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app.compliance.catalog import POR_ID
from app.providers.base import (
    TIPOS_CANONICOS, ActivityProvider, Capacidad, CapacidadNoSoportada, CostProvider, CostoDiario, IacStateProvider,
    InventoryProvider, Proveedor, ProveedorError, SecurityProvider, resumen_capacidades,
)

from .proveedores import FabricaAzure, FabricaMemoria, hoy, uids

FABRICAS = ["azure", "memoria"]
SEVERIDADES = {"critica", "alta", "media"}
INTERFAZ = {
    Capacidad.INVENTARIO: InventoryProvider, Capacidad.COSTOS: CostProvider, Capacidad.SEGURIDAD: SecurityProvider,
    Capacidad.IAC: IacStateProvider, Capacidad.ACTIVIDAD: ActivityProvider,
}


@pytest.fixture(params=FABRICAS)
def fabrica(request, monkeypatch, tmp_path):
    return FabricaAzure(monkeypatch, tmp_path) if request.param == "azure" else FabricaMemoria()


def prefijo(fabrica) -> str:
    return f"{fabrica.nombre}:"


# ---------------------------------------------------------------- identidad y capacidades

def test_declara_su_nombre_y_capacidades(fabrica):
    p = fabrica.normal()
    assert isinstance(p, Proveedor) and p.nombre == fabrica.nombre
    caps = p.capacidades()
    assert isinstance(caps, frozenset) and caps <= set(Capacidad)
    # Cada capacidad declarada se respalda con su interfaz.
    for c in caps:
        assert isinstance(p, INTERFAZ[c]), f"{p.nombre} declara {c.value} sin implementar {INTERFAZ[c].__name__}"
    assert set(resumen_capacidades(p)) == {c.value for c in Capacidad}


def test_una_capacidad_no_declarada_se_rechaza_no_se_vacia(fabrica):
    p = fabrica.sin_iac()
    assert Capacidad.IAC not in p.capacidades()
    with pytest.raises(CapacidadNoSoportada):
        p.recursos_gestionados()


# ---------------------------------------------------------------- inventario

def test_cuentas_canonicas(fabrica):
    cuentas = fabrica.normal().cuentas()
    assert cuentas, "el escenario tiene cuentas"
    assert len(uids(cuentas)) == len(cuentas)
    for c in cuentas:
        assert c.uid.startswith(prefijo(fabrica)) and c.provider == fabrica.nombre
        assert c.native_id and c.name


def test_recursos_canonicos(fabrica):
    p = fabrica.normal()
    cuentas = uids(p.cuentas())
    recursos = p.recursos(sorted(cuentas))
    assert recursos, "el escenario tiene recursos"
    assert len(uids(recursos)) == len(recursos), "un uid por recurso"
    for r in recursos:
        assert r.uid.startswith(prefijo(fabrica)) and r.provider == fabrica.nombre
        assert r.account_uid in cuentas
        assert r.native_type and r.native_type == r.native_type.lower()
        assert r.canonical_type is None or r.canonical_type in TIPOS_CANONICOS, r.canonical_type
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in r.tags.items())
    # Un tipo desconocido queda sin canónico, no con uno inventado.
    assert any(r.canonical_type is None for r in recursos)


def test_recursos_solo_de_las_cuentas_pedidas(fabrica):
    p = fabrica.normal()
    una = fabrica.cuenta_con_costos
    assert {r.account_uid for r in p.recursos([una])} == {una}
    assert p.recursos([]) == []


def test_rechaza_cuentas_de_otro_proveedor(fabrica):
    p = fabrica.normal()
    with pytest.raises(ValueError):
        p.recursos(["otra-nube:cuenta/1"])


def test_un_inventario_incompleto_es_un_error_no_una_lista_vacia(fabrica):
    p = fabrica.inventario_roto()
    with pytest.raises(ProveedorError):
        p.recursos([fabrica.cuenta_con_costos])


# ---------------------------------------------------------------- costos

def test_costos_en_focus(fabrica):
    p = fabrica.normal()
    pedidas = sorted(uids(p.cuentas()))
    r = p.costos_diarios(pedidas, 7)
    assert r.filas, "el escenario tiene gasto"
    claves = set()
    for f in r.filas:
        assert isinstance(f, CostoDiario)
        assert isinstance(f.billed_cost, Decimal) and isinstance(f.effective_cost, Decimal)
        assert len(f.currency) == 3 and f.currency.isupper()
        assert f.charge_date <= hoy() + timedelta(days=1)
        assert f.account_uid in r.cobertura.cubiertas, "solo filas de cuentas cubiertas"
        assert f.resource_uid == "" or f.resource_uid.startswith(prefijo(fabrica))
        clave = (f.charge_date, f.account_uid, f.resource_uid, f.service_name)
        assert clave not in claves, f"fila repetida: {clave}"
        claves.add(clave)
    # Un cargo sin recurso (soporte, impuestos) se conserva con uid vacío.
    assert any(f.resource_uid == "" for f in r.filas)


def test_la_cobertura_dice_que_cuentas_no_tienen_dato(fabrica):
    p = fabrica.normal()
    pedidas = sorted(uids(p.cuentas()))
    c = p.costos_diarios(pedidas, 7).cobertura
    grupos = [set(c.cubiertas), set(c.denegadas), set(c.fallidas)]
    assert set().union(*grupos) == set(pedidas), "toda cuenta pedida está en algún grupo"
    assert sum(len(g) for g in grupos) == len(pedidas), "y en uno solo"
    assert fabrica.cuenta_sin_permiso_de_costos in c.denegadas
    assert fabrica.cuenta_con_costos in c.cubiertas


# ---------------------------------------------------------------- seguridad

def test_hallazgos_del_catalogo(fabrica):
    p = fabrica.normal()
    r = p.evaluar_reglas(sorted(uids(p.cuentas())))
    assert r.hallazgos and not r.reglas_sin_evidencia
    claves = set()
    for h in r.hallazgos:
        assert h.rule_id in POR_ID, f"regla fuera del catálogo: {h.rule_id}"
        assert h.severity in SEVERIDADES
        assert h.resource_uid.startswith(prefijo(fabrica)) and h.account_uid.startswith(prefijo(fabrica))
        assert (h.rule_id, h.resource_uid) not in claves
        claves.add((h.rule_id, h.resource_uid))
        # Detalle plano y serializable: nada de estructuras nativas.
        json.dumps(dict(h.details))
        assert all(not isinstance(v, (dict, list)) for v in h.details.values())


def test_una_regla_sin_evaluar_se_informa(fabrica):
    p = fabrica.regla_sin_evidencia()
    r = p.evaluar_reglas(sorted(uids(p.cuentas())))
    assert fabrica.regla_que_puede_fallar in r.reglas_sin_evidencia
    assert r.reglas_sin_evidencia <= set(POR_ID)
    assert not [h for h in r.hallazgos if h.rule_id == fabrica.regla_que_puede_fallar], (
        "una regla sin evidencia no entrega hallazgos a medias")
    # Las demás reglas siguen evaluándose.
    assert r.hallazgos


# ---------------------------------------------------------------- IaC y actividad

def test_recursos_gestionados_por_iac(fabrica):
    p = fabrica.normal()
    assert Capacidad.IAC in p.capacidades()
    gestionados = p.recursos_gestionados()
    assert isinstance(gestionados, frozenset) and gestionados
    assert all(u.startswith(prefijo(fabrica)) for u in gestionados)
    # Se cruzan con el inventario por uid.
    assert gestionados & uids(p.recursos(sorted(uids(p.cuentas()))))


def test_creaciones(fabrica):
    p = fabrica.normal()
    a = p.creaciones(sorted(uids(p.cuentas())))
    assert a.creaciones
    for c in a.creaciones:
        assert c.resource_uid.startswith(prefijo(fabrica)) and c.actor
    if a.desde and a.hasta:
        assert a.desde <= a.hasta


# ---------------------------------------------------------------- estabilidad

def test_resultados_deterministas(fabrica):
    p = fabrica.normal()
    cuentas = sorted(uids(p.cuentas()))
    orden = lambda xs: sorted(xs, key=repr)  # noqa: E731
    assert orden(p.recursos(cuentas)) == orden(p.recursos(cuentas))
    assert orden(p.costos_diarios(cuentas, 7).filas) == orden(p.costos_diarios(cuentas, 7).filas)
    assert orden(p.evaluar_reglas(cuentas).hallazgos) == orden(p.evaluar_reglas(cuentas).hallazgos)

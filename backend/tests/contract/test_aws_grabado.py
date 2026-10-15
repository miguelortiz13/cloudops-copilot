"""Lo propio de AWS que la batería común no ve: traducción de Resource Explorer y Organizations."""

import pytest
from botocore.exceptions import ClientError

from app.providers.aws.provider import AwsProvider
from app.providers.base import CapacidadNoSoportada

from .proveedores import ClienteAwsGrabado

VISTA = "arn:aws:resource-explorer-2:us-east-1:111111111111:view/v/1"
A, B = "aws:account/111111111111", "aws:account/222222222222"


def test_solo_cuentas_activas_de_la_organizacion():
    cuentas = AwsProvider(ClienteAwsGrabado(), VISTA).cuentas()
    assert [(c.uid, c.name) for c in cuentas] == [(A, "Laboratorio"), (B, "Cargas")]


def test_traduce_los_recursos_de_resource_explorer():
    recursos = {r.native_id: r for r in AwsProvider(ClienteAwsGrabado(), VISTA).recursos([A, B])}

    # Repetido entre páginas: uno solo, el primero (con sus tags).
    bucket = recursos["arn:aws:s3:::lab-datos"]
    assert (bucket.uid, bucket.name, bucket.canonical_type) == ("aws:arn:aws:s3:::lab-datos", "lab-datos", "storage.bucket")
    assert bucket.group_name == "pagos" and bucket.tags["Environment"] == "prod"

    vm = recursos["arn:aws:ec2:us-east-1:111111111111:instance/i-0abc123"]
    assert (vm.name, vm.canonical_type, vm.region) == ("web-1", "compute.vm", "us-east-1")

    rol = recursos["arn:aws:iam::111111111111:role/Lector"]
    assert (rol.name, rol.region, rol.canonical_type) == ("Lector", None, None)

    asg = recursos["arn:aws:autoscaling:us-east-2:222222222222:autoScalingGroup:1234:autoScalingGroupName/web"]
    assert (asg.native_type, asg.canonical_type, asg.account_uid) == ("autoscaling:autoscalinggroup", "compute.vm_scale_set", B)

    # La cuenta suspendida no se pidió: sus recursos no entran.
    assert not [r for r in recursos.values() if "333333333333" in r.account_uid]


class _SinOrganizacion(ClienteAwsGrabado):
    def __init__(self):
        super().__init__()
        self._servicio = ""

    def __call__(self, servicio):
        self._servicio = servicio
        return self

    def get_paginator(self, operacion):
        if operacion == "list_accounts":
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "ListAccounts")
        return super().get_paginator(operacion)

    def get_caller_identity(self):
        return {"Account": "111111111111"}


def test_cuenta_miembro_ve_solo_la_propia():
    assert [c.uid for c in AwsProvider(_SinOrganizacion(), VISTA).cuentas()] == [A]


def test_capacidades_pendientes_se_rechazan():
    p = AwsProvider(ClienteAwsGrabado(), VISTA)
    for llamada in (lambda: p.costos_diarios([A], 7), lambda: p.evaluar_reglas([A]),
                    lambda: p.recursos_gestionados(), lambda: p.creaciones([A])):
        with pytest.raises(CapacidadNoSoportada):
            llamada()


COSTOS = {"database": "lab_costos", "table": "focus", "workgroup": "lab-costos"}


def _con_costos(**kw):
    cliente = ClienteAwsGrabado(**kw)
    return AwsProvider(cliente, VISTA, costos=COSTOS, pausa=lambda s: None), cliente


def test_costos_desde_el_export_focus_con_athena():
    p, cliente = _con_costos()
    r = p.costos_diarios([A, B], 30)
    (sql,) = cliente.consultas
    assert '"lab_costos"."focus"' in sql and "billing_period >=" in sql
    assert "subaccountid IN ('111111111111', '222222222222')" in sql
    filas = {(f.account_uid, f.resource_uid): f for f in r.filas}
    s3 = filas[(A, "aws:arn:aws:s3:::lab-datos")]
    assert (str(s3.billed_cost), s3.currency, s3.service_name) == ("0.0231", "USD", "Amazon Simple Storage Service")
    # Un id que no es ARN se conserva por recurso; un cargo sin recurso, con uid vacío.
    assert filas[(A, "aws:i-0abc123")].effective_cost < filas[(A, "aws:i-0abc123")].billed_cost
    assert filas[(A, "")].service_name == "Tax"
    # Toda la organización está en el export: las dos cuentas quedan cubiertas.
    assert r.cobertura.cubiertas == [A, B] and not r.cobertura.fallidas


def test_si_athena_falla_las_cuentas_quedan_sin_dato():
    p, _ = _con_costos(athena_falla=True)
    r = p.costos_diarios([A], 7)
    assert r.filas == [] and r.cobertura.fallidas == [A] and r.cobertura.cubiertas == []


def test_ids_de_cuenta_se_validan_antes_de_ir_al_sql():
    p, cliente = _con_costos()
    with pytest.raises(ValueError):
        p.costos_diarios(["aws:account/1' OR '1'='1"], 7)
    assert cliente.consultas == []


def test_export_todavia_sin_entregar():
    assert _con_costos()[0].export_entregado() is True
    assert _con_costos(export_vacio=True)[0].export_entregado() is False

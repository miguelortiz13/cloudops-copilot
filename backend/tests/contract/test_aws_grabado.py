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

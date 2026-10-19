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
    for llamada in (lambda: p.costos_diarios([A], 7), lambda: p.recursos_gestionados(), lambda: p.creaciones([A])):
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


# ---------------------------------------------------------------- seguridad

def _seguridad(**kw):
    cliente = ClienteAwsGrabado(**kw)
    return AwsProvider(cliente, VISTA, rol_miembro="lab-reader", sesion=lambda c: cliente), cliente


def test_los_recursos_por_defecto_de_aws_no_se_inventarian():
    nombres = {r.name for r in AwsProvider(ClienteAwsGrabado(), VISTA).recursos([A, B])}
    assert "default.memorydb-redis7" not in nombres and "AWSServiceRoleForSupport" not in nombres
    # Lo que creó alguien sí, aunque se llame parecido.
    assert {"Lector", "bastion", "pagos"} <= nombres


def test_reglas_de_aws_sobre_la_cuenta():
    p, _ = _seguridad()
    r = p.evaluar_reglas([A, B])
    assert not r.reglas_sin_evidencia
    por_regla = {}
    for h in r.hallazgos:
        por_regla.setdefault(h.rule_id, []).append(h)
    (sg,) = por_regla["aws.network.admin-port-open"]
    # Abierto a internet en 22 y asociado a una interfaz: crítico. El de 443 y el de 22 desde 10/8 no.
    assert sg.resource_uid.endswith("security-group/sg-abierto") and sg.severity == "critica"
    assert (sg.details["port"], sg.details["source"], sg.details["asociado"]) == (22, "0.0.0.0/0", True)
    # La cuenta no bloquea el acceso público y el bucket lo bloquea a medias.
    (s3,) = por_regla["aws.storage.public-access-not-blocked"]
    assert s3.resource_uid == "aws:arn:aws:s3:::lab-datos" and s3.severity == "alta"
    assert por_regla["aws.database.public-network"][0].details["engine"] == "postgres"
    # Un volumen sin cifrar y suelto: un hallazgo de seguridad y uno de costo.
    assert len(por_regla["aws.storage.disk-unencrypted"]) == len(por_regla["aws.cost.unattached-volume"]) == 1
    assert por_regla["aws.cost.unassociated-elastic-ip"][0].details["ip"] == "203.0.113.10"
    # Root con MFA: sin hallazgo.
    assert "aws.identity.root-without-mfa" not in por_regla


def test_root_sin_mfa_es_critico():
    p, cliente = _seguridad()
    cliente._datos["get_account_summary"] = {"SummaryMap": {"AccountMFAEnabled": 0}}
    (h,) = [h for h in p.evaluar_reglas([A]).hallazgos if h.rule_id == "aws.identity.root-without-mfa"]
    assert (h.resource_uid, h.severity) == ("aws:arn:aws:iam::111111111111:root", "critica")


def test_la_cuenta_que_bloquea_el_acceso_publico_cubre_todos_sus_buckets():
    p, cliente = _seguridad()
    completo = {"PublicAccessBlockConfiguration": dict.fromkeys(
        ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"), True)}
    cliente.get_public_access_block = lambda **kw: completo
    assert not [h for h in p.evaluar_reglas([A]).hallazgos if h.rule_id == "aws.storage.public-access-not-blocked"]


def test_cuenta_miembro_sin_rol_de_lectura_queda_sin_evidencia():
    cliente = ClienteAwsGrabado()
    p = AwsProvider(cliente, VISTA, sesion=lambda c: cliente)  # sin rol_miembro: el StackSet no se desplegó
    r = p.evaluar_reglas([A, B])
    assert "aws.network.admin-port-open" in r.reglas_sin_evidencia
    # La cuenta del hub igual se evalúa.
    assert any(h.account_uid == A for h in r.hallazgos)


@pytest.mark.parametrize("arn, nombre", [
    ("arn:aws:s3:::lab-datos", "lab-datos"),
    ("arn:aws:ec2:us-east-1:111111111111:instance/i-0abc", "i-0abc"),
    ("arn:aws:rds:us-east-1:111111111111:db:pagos", "pagos"),
    ("arn:aws:lambda:us-east-1:111111111111:function:web", "web"),
    ("arn:aws:iam::111111111111:role/equipo/Lector", "Lector"),
    ("arn:aws:resource-explorer-2:us-east-1:111111111111:view/inventario/2adc0db4", "inventario"),
    ("arn:aws:apprunner:us-east-1:111111111111:autoscalingconfiguration/DefaultConfiguration/1/0001", "DefaultConfiguration"),
    ("arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/web/50dc6c49", "web"),
    ("arn:aws:autoscaling:us-east-2:222222222222:autoScalingGroup:1234:autoScalingGroupName/web", "web"),
])
def test_nombre_desde_el_arn(arn, nombre):
    from app.providers.aws.provider import _nombre

    assert _nombre(arn, {}) == nombre


@pytest.mark.parametrize("tipo, nombre, arn", [
    ("resource-explorer-2:view", "us-east-2", "arn:aws:resource-explorer-2:us-east-2:1:view/us-east-2/bb68"),
    ("iam:saml-provider", "AWSSSO_f76f_DO_NOT_DELETE", "arn:aws:iam::1:saml-provider/AWSSSO_f76f_DO_NOT_DELETE"),
    ("iam:role", "AWSReservedSSO_Admin", "arn:aws:iam::1:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_Admin"),
    ("elasticache:user", "default.iam-user", "arn:aws:elasticache:us-east-1:1:user:default.iam-user"),
])
def test_recursos_por_defecto(tipo, nombre, arn):
    from app.providers.aws.provider import es_por_defecto

    assert es_por_defecto(tipo, nombre, arn)
    assert not es_por_defecto("resource-explorer-2:view", "inventario", "arn:aws:resource-explorer-2:us-east-1:1:view/inventario/2adc")

"""
Reglas del catálogo (app/compliance/catalog.py) evaluadas sobre AWS con
llamadas de lectura gratuitas: sin Security Hub ni AWS Config, que cobran.

Cada regla mira solo los recursos que el inventario (Resource Explorer) ya
encontró, en sus regiones: no recorre las regiones vacías ni choca con las
SCP que las bloquean. Si la llamada de una regla falla, la regla queda sin
evidencia y sus hallazgos previos no se dan por resueltos.
"""

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Set, Tuple

from app.compliance.catalog import CONSULTA_DE_TIPO, REGLAS
from app.providers.base import Hallazgo, Recurso

PUERTOS_DE_ADMINISTRACION = (22, 3389)
ABIERTO = ("0.0.0.0/0", "::/0")
LOTE = 200  # ids por llamada Describe*

Cliente = Callable[..., Any]


def _id(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def _por_region(recursos: Iterable[Recurso], tipo: str) -> Dict[str, List[Recurso]]:
    grupos: Dict[str, List[Recurso]] = defaultdict(list)
    for r in recursos:
        if r.native_type == tipo and r.region:
            grupos[r.region].append(r)
    return grupos


def _lotes(items: List[Any]) -> Iterable[List[Any]]:
    for i in range(0, len(items), LOTE):
        yield items[i:i + LOTE]


def _codigo(e: Exception) -> str:
    return getattr(e, "response", {}).get("Error", {}).get("Code", "")


def _abre_administracion(permiso: Dict[str, Any]) -> Tuple[int, str] | None:
    """(puerto, origen) si la regla de entrada abre SSH o RDP a todo internet."""
    origenes = [r.get("CidrIp") for r in permiso.get("IpRanges") or []] + \
               [r.get("CidrIpv6") for r in permiso.get("Ipv6Ranges") or []]
    abierto = next((o for o in origenes if o in ABIERTO), None)
    if abierto is None:
        return None
    if permiso.get("IpProtocol") == "-1":
        return PUERTOS_DE_ADMINISTRACION[0], abierto
    if permiso.get("IpProtocol") not in ("tcp", "6"):
        return None
    desde, hasta = permiso.get("FromPort", 0), permiso.get("ToPort", 65535)
    puerto = next((p for p in PUERTOS_DE_ADMINISTRACION if desde <= p <= hasta), None)
    return (puerto, abierto) if puerto else None


def security_groups(cliente: Cliente, recursos: List[Recurso]) -> List[Hallazgo]:
    regla = REGLAS["aws_sg"]
    hallazgos = []
    for region, grupos in _por_region(recursos, "ec2:security-group").items():
        ec2 = cliente("ec2", region_name=region)
        por_id = {_id(r.native_id): r for r in grupos}
        abiertos: Dict[str, Tuple[Recurso, int, str]] = {}
        for lote in _lotes(list(por_id)):
            for g in ec2.describe_security_groups(GroupIds=lote)["SecurityGroups"]:
                for permiso in g.get("IpPermissions") or []:
                    abre = _abre_administracion(permiso)
                    if abre and g["GroupId"] in por_id:
                        abiertos[g["GroupId"]] = (por_id[g["GroupId"]], *abre)
                        break
        asociados: Set[str] = set()
        if abiertos:
            interfaces = ec2.describe_network_interfaces(Filters=[{"Name": "group-id", "Values": list(abiertos)}])
            asociados = {g["GroupId"] for i in interfaces["NetworkInterfaces"] for g in i.get("Groups") or []}
        for gid, (r, puerto, origen) in abiertos.items():
            hallazgos.append(Hallazgo(regla.id, r.uid, r.account_uid, "critica" if gid in asociados else "alta",
                                      {"name": r.name, "region": region, "port": puerto, "source": origen,
                                       "asociado": gid in asociados}))
    return hallazgos


def s3(cliente: Cliente, recursos: List[Recurso], cuenta: str) -> List[Hallazgo]:
    regla = REGLAS["aws_s3"]

    def bloqueado(config: Dict[str, Any]) -> bool:
        return all(config.get(k) for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"))

    try:
        cuenta_bloquea = bloqueado(cliente("s3control").get_public_access_block(AccountId=cuenta)["PublicAccessBlockConfiguration"])
    except Exception as e:
        if _codigo(e) != "NoSuchPublicAccessBlockConfiguration":
            raise
        cuenta_bloquea = False
    if cuenta_bloquea:
        return []  # la cuenta bloquea el acceso público de todos sus buckets

    hallazgos = []
    for region, buckets in _por_region(recursos, "s3:bucket").items():
        s3c = cliente("s3", region_name=region)
        for r in buckets:
            try:
                propio = bloqueado(s3c.get_public_access_block(Bucket=r.name)["PublicAccessBlockConfiguration"])
            except Exception as e:
                if _codigo(e) != "NoSuchPublicAccessBlockConfiguration":
                    raise
                propio = False
            if propio:
                continue
            try:
                publico = bool(s3c.get_bucket_policy_status(Bucket=r.name)["PolicyStatus"].get("IsPublic"))
            except Exception as e:
                if _codigo(e) != "NoSuchBucketPolicy":
                    raise
                publico = False
            hallazgos.append(Hallazgo(regla.id, r.uid, r.account_uid, "critica" if publico else "alta",
                                      {"name": r.name, "region": region, "publico": publico}))
    return hallazgos


def rds(cliente: Cliente, recursos: List[Recurso]) -> List[Hallazgo]:
    regla = REGLAS["aws_rds"]
    hallazgos = []
    for region, instancias in _por_region(recursos, "rds:db").items():
        por_arn = {r.native_id: r for r in instancias}
        for pagina in cliente("rds", region_name=region).get_paginator("describe_db_instances").paginate():
            for db in pagina["DBInstances"]:
                r = por_arn.get(db.get("DBInstanceArn"))
                if r and db.get("PubliclyAccessible"):
                    hallazgos.append(Hallazgo(regla.id, r.uid, r.account_uid, regla.severity_default,
                                              {"name": r.name, "region": region, "engine": db.get("Engine")}))
    return hallazgos


def ebs(cliente: Cliente, recursos: List[Recurso]) -> List[Hallazgo]:
    """Volúmenes sin cifrar (seguridad) y sin adjuntar (costo): una sola llamada para las dos reglas."""
    sin_cifrar, libre = REGLAS["aws_ebs"], REGLAS["aws_ebs_libre"]
    hallazgos = []
    for region, volumenes in _por_region(recursos, "ec2:volume").items():
        por_id = {_id(r.native_id): r for r in volumenes}
        ec2 = cliente("ec2", region_name=region)
        for lote in _lotes(list(por_id)):
            for v in ec2.describe_volumes(VolumeIds=lote)["Volumes"]:
                r = por_id.get(v["VolumeId"])
                if r is None:
                    continue
                detalle = {"name": r.name, "region": region, "size_gb": v.get("Size"), "type": v.get("VolumeType")}
                if not v.get("Encrypted"):
                    hallazgos.append(Hallazgo(sin_cifrar.id, r.uid, r.account_uid, sin_cifrar.severity_default, detalle))
                if v.get("State") == "available":
                    hallazgos.append(Hallazgo(libre.id, r.uid, r.account_uid, libre.severity_default, detalle))
    return hallazgos


def eips(cliente: Cliente, recursos: List[Recurso]) -> List[Hallazgo]:
    regla = REGLAS["aws_eip_libre"]
    hallazgos = []
    for region, ips in _por_region(recursos, "ec2:elastic-ip").items():
        por_id = {_id(r.native_id): r for r in ips}
        for a in cliente("ec2", region_name=region).describe_addresses()["Addresses"]:
            r = por_id.get(a.get("AllocationId"))
            if r and not a.get("AssociationId"):
                hallazgos.append(Hallazgo(regla.id, r.uid, r.account_uid, regla.severity_default,
                                          {"name": r.name, "region": region, "ip": a.get("PublicIp")}))
    return hallazgos


def root_sin_mfa(cliente: Cliente, cuenta: str, account_uid: str, resource_uid: Callable[[str], str]) -> List[Hallazgo]:
    regla = REGLAS["aws_root"]
    resumen = cliente("iam").get_account_summary()["SummaryMap"]
    if resumen.get("AccountMFAEnabled"):
        return []
    return [Hallazgo(regla.id, resource_uid(f"arn:aws:iam::{cuenta}:root"), account_uid, regla.severity_default,
                     {"name": "root"})]


def reglas_de(consulta: str) -> Set[str]:
    """Ids de las reglas que alimenta una consulta (si falla, quedan sin evidencia)."""
    return {REGLAS[t].id for t, c in CONSULTA_DE_TIPO.items() if c == consulta and REGLAS[t].proveedor == "aws"}

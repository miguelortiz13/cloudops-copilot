"""Tipos de Resource Explorer (servicio:tipo, en minúsculas) -> tipo canónico."""

from typing import Optional

TIPOS = {
    "ec2:instance": "compute.vm",
    "autoscaling:autoscalinggroup": "compute.vm_scale_set",
    "lambda:function": "compute.app",
    "ecs:cluster": "compute.container_platform",
    "eks:cluster": "kubernetes.cluster",
    "ecr:repository": "container.registry",
    "s3:bucket": "storage.bucket",
    "ec2:volume": "storage.disk",
    "ec2:snapshot": "storage.snapshot",
    "ec2:vpc": "network.vnet",
    "ec2:network-interface": "network.interface",
    "ec2:elastic-ip": "network.public_ip",
    "ec2:security-group": "network.firewall_rules",
    "elasticloadbalancing:loadbalancer": "network.load_balancer",
    "rds:cluster": "database.server",
    "rds:db": "database.sql",
    "dynamodb:table": "database.nosql",
    "secretsmanager:secret": "secrets.vault",
    "kms:key": "secrets.vault",
    "logs:log-group": "observability.logs",
}


def canonical_type(native_type: str) -> Optional[str]:
    return TIPOS.get((native_type or "").lower())

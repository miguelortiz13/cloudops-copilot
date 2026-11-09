# Runbook: despliegue atascado (KubeDeploymentRolloutStuck)

Alertas: `KubeDeploymentRolloutStuck`, `KubeDeploymentReplicasMismatch`. Una revisión nueva no termina de reemplazar a la anterior.

## Síntomas

- `kubectl rollout status deployment/<deployment> -n <ns>` no termina o dice `progress deadline exceeded`.
- Conviven pods de la revisión nueva (que no quedan listos) y de la anterior.

## Diagnóstico

1. ¿Por qué no quedan listos los pods nuevos? Casi siempre es otra alerta con su propio runbook: imagen que no se descarga (ImagePullBackOff), CrashLoopBackOff u OOMKilled.
2. Si quedan `Pending`, no hay recursos en el clúster: `kubectl describe pod` dice `Insufficient cpu` o `Insufficient memory`.
3. Ver qué cambió entre revisiones: `kubectl rollout history deployment/<deployment> -n <ns> --revision=<n>` o `cambios_recientes` en el panel.

## Resolución

- Volver a la revisión que funcionaba: `kubectl rollout undo deployment/<deployment> -n <ns>`.
- Corregir la causa (imagen, configuración, recursos) y desplegar de nuevo.
- Sin recursos: reducir los `requests`, escalar el clúster o liberar cargas.

## Verificación

- `kubectl rollout status` termina y la revisión vigente tiene todas sus réplicas listas.

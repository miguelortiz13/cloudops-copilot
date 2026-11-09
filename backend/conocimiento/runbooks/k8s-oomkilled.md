# Runbook: contenedor sin memoria (OOMKilled)

Alertas: `KubePodCrashLooping`, `PodCrashLooping`, a veces `KubeContainerOOMKilled`. El kernel mata el contenedor porque superó su límite de memoria.

## Síntomas

- `kubectl describe pod` muestra *Last State: Terminated, Reason: OOMKilled, Exit Code: 137*.
- El log se corta de golpe (a veces con `Killed`) mientras la aplicación carga datos o atiende un pico.
- Reinicios que suben y, con el tiempo, `CrashLoopBackOff`.

## Diagnóstico

1. Confirmar el motivo: `kubectl get pod <pod> -n <ns> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'`.
2. Comparar el consumo real con el límite: `kubectl top pod <pod> -n <ns>` y `resources.limits.memory` del Deployment.
3. ¿Cambió algo? Una versión nueva que carga más datos, más tráfico o un límite que alguien bajó.

## Resolución

- **Límite demasiado bajo para la carga normal**: subir `resources.limits.memory` (y `requests` acorde) en el manifiesto y desplegar.
- **Fuga de memoria o versión nueva que consume más**: volver a la revisión anterior con `kubectl rollout undo` y abrir el defecto.
- **Nodo sin memoria** (varios pods expulsados, `MemoryPressure`): ver el runbook de nodo con problemas.

## Verificación

- El contenedor deja de reiniciarse y `kubectl top` queda por debajo del límite con margen.

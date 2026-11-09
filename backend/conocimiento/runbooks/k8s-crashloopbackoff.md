# Runbook: pod en CrashLoopBackOff

Alertas: `PodCrashLooping`, `KubePodCrashLooping`. El contenedor arranca, falla y Kubernetes lo reinicia con esperas cada vez más largas.

## Síntomas

- El pod está `Running` o `Error` con reinicios que suben y motivo `CrashLoopBackOff`.
- Eventos `BackOff: Back-off restarting failed container`.
- La carga (Deployment) tiene menos réplicas listas que las deseadas.

## Diagnóstico

1. Log del intento anterior, que es el que falló: `kubectl logs <pod> -n <ns> --previous`.
2. Motivo y código de salida del último estado: `kubectl describe pod <pod> -n <ns>` (sección *Last State*). Código 137 es OOMKilled (ver el runbook de OOMKilled); 1 o 2 es un error de la aplicación.
3. Cambios recientes: ¿hubo una revisión nueva del Deployment minutos antes de la alerta? En el panel, *Activos → Kubernetes → clúster* o la herramienta `cambios_recientes`. Un despliegue justo antes es el primer sospechoso.
4. Dependencias: si el log dice `connection refused`, `timeout` o `no such host`, revisa el servicio del que depende (endpoints, pods listos).

## Causas frecuentes y resolución

- **Error de configuración tras un despliegue** (excepción al arrancar, variable o ConfigMap faltante): volver a la revisión anterior con `kubectl rollout undo deployment/<deployment> -n <ns>` y corregir en el repositorio.
- **Dependencia caída** (`Connection refused` a una base o a redis, por ejemplo `redis-cart:6379`): el pod no es la causa. Revisa el pod de la dependencia, su servicio y sus endpoints (`kubectl get endpoints <servicio> -n <ns>`). Cuando la dependencia vuelve, el pod se recupera solo.
- **Secreto o volumen faltante**: el evento lo dice (`secret "x" not found`). Crear el secreto o corregir el nombre en el manifiesto.
- **Sondas demasiado estrictas** (liveness mata un arranque lento): subir `initialDelaySeconds` o usar `startupProbe`.

## Verificación

- `kubectl rollout status deployment/<deployment> -n <ns>` termina y los reinicios dejan de subir.
- La alerta se resuelve sola en Alertmanager; el incidente pasa a *resuelto* y conviene marcar si el diagnóstico fue correcto.

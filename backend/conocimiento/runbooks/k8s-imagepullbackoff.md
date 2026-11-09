# Runbook: imagen que no se puede descargar (ImagePullBackOff)

Alertas: `KubePodNotReady`, `PodNotReady`, `KubeDeploymentRolloutStuck`. El pod queda `Pending` con motivo `ImagePullBackOff` o `ErrImagePull`.

## Síntomas

- Evento `Failed to pull image "<registro>/<imagen>:<tag>": not found`, `manifest unknown`, `unauthorized` o `i/o timeout`.
- Casi siempre aparece justo después de una revisión nueva del Deployment: el cambio de imagen es la causa.

## Diagnóstico

1. `kubectl describe pod <pod> -n <ns>`: el evento `Failed` dice la imagen exacta y el error.
2. Compara la imagen nueva con la de la revisión anterior (*Activos → Kubernetes* o `cambios_recientes`): un tag que no existe (`v9.9.9`), un registro distinto o un error de tipeo.
3. Si el error es `unauthorized`, el clúster no tiene credenciales para ese registro (`imagePullSecrets` o identidad del nodo).

## Resolución

- **Tag inexistente o mal escrito**: `kubectl rollout undo deployment/<deployment> -n <ns>` para volver a la imagen anterior, y corregir el tag en el repositorio o publicar la imagen que falta.
- **Sin credenciales**: agregar el `imagePullSecret` al ServiceAccount o dar a la identidad del clúster permiso de lectura (en Azure, rol `AcrPull` sobre el ACR).
- **Registro caído o sin red**: comprobar desde un nodo que el registro responde; si es general, abrir el caso con el proveedor.

## Verificación

- El pod nuevo pasa a `Running` y la carga muestra todas sus réplicas listas.
- La revisión que quedó vigente usa la imagen correcta.

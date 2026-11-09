# Runbook: nodo caído o con presión (NodeNotReady)

Alertas: `KubeNodeNotReady`, `KubeNodeUnreachable`, y una tormenta de `PodNotReady` en varios namespaces a la vez.

## Síntomas

- `kubectl get nodes` muestra el nodo `NotReady`; eventos `NodeNotReady`.
- Pods del nodo en `Unknown` o `Terminating`; pods nuevos `Pending` porque no hay dónde ubicarlos.
- Muchas alertas de pods casi al mismo tiempo: el panel las agrupa como **tormenta** y las diagnostica juntas. La causa común es el nodo, no cada pod.

## Diagnóstico

1. `kubectl describe node <nodo>`: condiciones (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`) y desde cuándo.
2. ¿El kubelet responde? En un laboratorio local (kind, minikube) suele ser la máquina o Docker reiniciados; en la nube, la VM detenida o actualizándose.
3. Revisar si afecta a un solo nodo o a todos (red del clúster, plano de control).

## Resolución

- **VM o máquina reiniciada**: esperar a que el nodo vuelva; si no vuelve en minutos, reiniciar el servicio del kubelet o la VM.
- **Presión de disco**: liberar imágenes y logs (`crictl rmi --prune`), ampliar el disco.
- **Presión de memoria**: ver qué pods consumen más; poner límites o mover cargas.
- Para sacar el nodo de servicio: `kubectl cordon <nodo>` y `kubectl drain <nodo> --ignore-daemonsets`.

## Verificación

- El nodo vuelve a `Ready`, los pods `Pending` se ubican y las alertas de la tormenta se resuelven juntas.

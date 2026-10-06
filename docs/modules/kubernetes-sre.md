# Kubernetes SRE

Código: [`services/k8s_service.py`](../../backend/app/services/k8s_service.py), [`routers/k8s.py`](../../backend/app/routers/k8s.py).

## Qué ofrece

- **Overview:** nodos, pods por estado, servicios y un score de salud del clúster (0-100).
- **Incidencias**, clasificadas por severidad y con la acción recomendada:
  - pods fuera de `Running`/`Succeeded` (p. ej. `Pending`), en `CrashLoopBackOff` u `OOMKilled`, o con más de 5 reinicios (crítica si además superan 10);
  - nodos `NotReady` (crítica) o con `MemoryPressure`, `DiskPressure` o `NetworkUnavailable`;
  - servicios sin endpoints (normalmente, selectores que no coinciden con los labels del deployment).
- **Logs:** últimas líneas de un pod o contenedor.
- **Chat SRE:** preguntas en lenguaje natural con el contexto del clúster; sugiere comandos `kubectl`.

## Conexión

Usa **AKS Run Command** a través del SDK de Azure: no requiere exponer el API server ni distribuir kubeconfig. Configuración:

```env
K8S_CLUSTER_NAME=aks-plataforma-dev
K8S_RESOURCE_GROUP=rg-plataforma-dev
K8S_SUBSCRIPTION_ID=<suscripción>
```

Con alguna vacía el agente queda en modo *offline* y los endpoints lo indican. `GET /api/k8s/clusters` lista los clústeres visibles para ayudar a configurarlo.

La identidad necesita poder invocar Run Command sobre el clúster (`Microsoft.ContainerService/managedClusters/runCommand/action`, incluido en `Azure Kubernetes Service Cluster User Role` junto con permisos de lectura en el clúster).

## Seguridad

Es el único camino de la plataforma que ejecuta algo dentro de un recurso. Por eso:

- los comandos los construye el servicio y son de lectura;
- los nombres que llegan del cliente se validan contra RFC 1123;
- cualquier metacarácter de shell en el comando final provoca un rechazo antes de llamar a Azure.

Detalle en [security.md](../security.md#agente-sre-de-kubernetes).

## Límites

Run Command tarda varios segundos por invocación; el overview no es en tiempo real. Para monitoreo continuo usa Container Insights o Prometheus; este agente está pensado para diagnóstico bajo demanda.

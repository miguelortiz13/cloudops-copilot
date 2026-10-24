# Kubernetes

Código: [`k8s-agent/`](../../k8s-agent) (agente), [`services/k8s_fleet.py`](../../backend/app/services/k8s_fleet.py) (incidencias), [`routers/k8s.py`](../../backend/app/routers/k8s.py) y la página *Kubernetes* del panel. Diseño y partes pendientes: [plan del módulo](../plan/08-kubernetes.md).

La plataforma ve cada clúster a través de un **agente de solo lectura que corre dentro de él**. Cada 5 minutos el agente arma una foto del estado y la sube a Azure Storage; la plataforma nunca entra al clúster. Así funciona igual en AKS, EKS o un clúster fuera de la nube (homelab con k3s, kubeadm, Talos, RKE2…), sin abrir puertos ni exponer el API server.

## Qué muestra

- **Clústeres** con su distribución, versión, nodos listos, pods en ejecución, score de salud (0-100) y la antigüedad de la última foto. Si la foto tiene más de 15 minutos, el panel avisa que el agente dejó de reportar.
- **Incidencias**, con severidad y el siguiente paso sugerido:

| Incidencia | Severidad |
|---|---|
| Nodo que no está `Ready` | Crítica |
| Nodo con `MemoryPressure`, `DiskPressure`, `PIDPressure` o `NetworkUnavailable` | Alta |
| Pod en `CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff`, `ErrImagePull` o error de configuración del contenedor | Alta; crítica con más de 10 reinicios |
| Pod `Pending`, `Failed` o `Unknown` por más de 10 minutos | Alta (media si es de un Job) |
| Pod con más de 5 reinicios, o en ejecución pero no listo por más de 10 minutos; pod desalojado | Media |
| Deployment, StatefulSet o DaemonSet con menos réplicas listas que las deseadas | Alta si no tiene ninguna; media si tiene algunas |
| Servicio con selector y sin ningún endpoint listo | Media |

- **Nodos** (estado, roles, versión, arquitectura, CPU y memoria), **cargas** (las degradadas primero), **pods con problemas** con sus últimas líneas de log (*Ver log*) y los **eventos de advertencia** más recientes.

El score resta 25 por incidencia crítica, 10 por alta y 4 por media.

## Logs de los pods con problemas

En cada foto, el agente agrega las últimas 40 líneas de hasta 10 pods con problemas (CrashLoop, OOMKilled, error de imagen o de configuración, reinicios sin estar listo, o fallidos). Si el contenedor se reinició, toma las de la **ejecución anterior**, que es donde está el error. Antes de enviar enmascara lo que parece una credencial (`password=`, `token:`, `api_key=`, `Authorization: Bearer …`, llaves de AWS) y corta cada línea a 300 caracteres.

Las líneas salen del clúster hacia el almacenamiento de la plataforma. Si tus aplicaciones escriben datos sensibles en sus logs, desactívalo con `INCLUDE_LOGS=false` en el Deployment del agente.

## Avisos

El job `k8s-watch` revisa las fotos cada 10 minutos (`kubernetes_watch_cron`) y avisa al mismo webhook de los [avisos](notifications-reports.md) (Discord, Slack o Teams):

| Aviso | Cuándo |
|---|---|
| Incidencia nueva | Una incidencia crítica o alta aparece en dos fotos seguidas. Así no avisa de un pod que solo estaba arrancando ni de un despliegue en curso |
| Resuelta | La incidencia avisada deja de aparecer |
| El agente dejó de reportar | La última foto tiene más de 15 minutos (nodo apagado, clúster detenido o sin salida a Internet) |
| El agente volvió a reportar | Llega una foto nueva después del aviso anterior |

Cada aviso sale una sola vez; el estado vive en el File Share (`k8s_watch.json`), sin abrir la base. Entre que aparece un problema y llega el aviso pasan entre 10 y 20 minutos. El job solo existe si hay clústeres y webhook configurados, y cuesta unos segundos de 0,25 vCPU por ejecución, dentro del cupo gratuito.

## Chat SRE

El agente *Kubernetes* de la consola (rol operador) responde sobre la última foto: incidencias, pods con problemas y sus logs, cargas degradadas, nodos y eventos. Explica la causa probable citando la evidencia y sugiere comandos `kubectl`; no ejecuta nada en el clúster. Si hay varios clústeres, usa el que nombre la pregunta o el primero que reporte. Sin modelo de lenguaje responde con las incidencias y su siguiente paso.

## Conectar un clúster

1. **Declararlo en Terraform** (`terraform.tfvars`):

    ```hcl
    kubernetes_clusters = ["homelab"]
    ```

    Exporta antes `TF_VAR_notify_webhook_url` (ver [operación](../operations.md#cambios-de-infraestructura)) y aplica. Se crean el contenedor `k8s-homelab`, su SAS de solo escritura y el permiso de lectura del API.

2. **Obtener la URL de subida** (es una credencial: no la pegues en chats ni en el repositorio):

    ```bash
    terraform output -json kubernetes_agent_upload_urls | jq -r .homelab
    ```

3. **Crear el secret y desplegar el agente** en el clúster:

    ```bash
    kubectl create namespace cloudops
    kubectl -n cloudops create secret generic cloudops-agent \
      --from-literal=cluster-name=homelab \
      --from-literal=upload-url="<URL del paso 2>"
    kubectl apply -k k8s-agent/
    ```

4. **Comprobar**: `kubectl -n cloudops logs deploy/cloudops-agent` muestra `foto subida` cada 5 minutos, y el clúster aparece en *Kubernetes* en el panel.

Para ver la foto sin subirla: `kubectl -n cloudops exec deploy/cloudops-agent -- python /agent/agent.py --print`.

### Requisitos del clúster

- Salida HTTPS hacia `*.blob.core.windows.net`. Si sale por un proxy, agrega `HTTPS_PROXY` al Deployment; el agente no usa el proxy para hablar con el API del clúster.
- Poder descargar la imagen oficial `python:3.13-alpine` (arm64 y amd64).
- Unos 10m de CPU y 48 MiB de memoria.

## Seguridad

| Control | Detalle |
|---|---|
| Solo lectura | El ClusterRole tiene `get` y `list` sobre nodos, namespaces, pods, servicios, eventos, cargas de `apps` y EndpointSlices, y `get` sobre `pods/log`. Nunca lee `secrets` ni `configmaps` |
| Poco y nada sensible en la foto | Por pod solo viaja el estado, el dueño y, por contenedor, la imagen y dos banderas (si tiene límites y si es privilegiado). Ni variables de entorno, ni comandos, ni volúmenes. Los logs de los pods con problemas van enmascarados y se pueden desactivar (`INCLUDE_LOGS=false`) |
| Contenedor endurecido | Sin root (UID 65534), sistema de archivos de solo lectura, sin capacidades, sin escalada de privilegios, `seccomp` por defecto |
| Credencial mínima | Cada clúster tiene su propio contenedor y una SAS que solo puede crear y escribir en él: no puede leer ni listar nada. Vence en `kubernetes_agent_sas_expiry` |
| Revocar | Rotar la clave de la cuenta de almacenamiento invalida todas las SAS; después, `terraform apply` y actualizar el secret en cada clúster |
| Sin código externo | El agente es un script con la biblioteca estándar de Python, legible en el repositorio y montado como ConfigMap |

## Costo

288 escrituras al día por clúster y unos KB por foto (comprimida): centavos al mes. El API solo lee la foto cuando alguien abre la página; ni el API ni la base se despiertan por los envíos del agente.

## Rutas heredadas (AKS Run Command)

`GET /api/k8s/health`, `GET /api/k8s/pod-logs` y `POST /api/k8s/incidents`, `/api/k8s/overview` y `/api/k8s/reinit` todavía usan AKS Run Command con `K8S_CLUSTER_NAME`, `K8S_RESOURCE_GROUP` y `K8S_SUBSCRIPTION_ID`; sin ellas quedan en modo *offline*. El panel ya no las usa y se retiran en la parte 5 del [plan](../plan/08-kubernetes.md#partes). Mientras existan mantienen sus controles: comandos de lectura construidos por el servicio, nombres validados contra RFC 1123 y rechazo de metacaracteres de shell ([seguridad](../security.md#agente-sre-de-kubernetes)).

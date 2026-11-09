# Runbooks

Los runbooks viven en [`backend/conocimiento/runbooks/`](../../backend/conocimiento/runbooks/) y la guía de uso del panel en [`backend/conocimiento/guia/`](../../backend/conocimiento/guia/): van dentro de la imagen del API porque son el corpus de la base de conocimiento de la IA ([plan 11, IA-4](../plan/11-plataforma-ia.md#5-rag-recuperación-de-conocimiento)). El diagnóstico de incidentes los cita en *Siguientes pasos* y el chat (y el servidor MCP) los encuentra con `buscar_conocimiento`.

| Runbook | Alertas o caso |
|---|---|
| [Pod en CrashLoopBackOff](../../backend/conocimiento/runbooks/k8s-crashloopbackoff.md) | `PodCrashLooping`, `KubePodCrashLooping` |
| [Imagen que no se puede descargar](../../backend/conocimiento/runbooks/k8s-imagepullbackoff.md) | `ImagePullBackOff`, `ErrImagePull` |
| [Contenedor sin memoria](../../backend/conocimiento/runbooks/k8s-oomkilled.md) | `OOMKilled`, código 137 |
| [Nodo caído o con presión](../../backend/conocimiento/runbooks/k8s-nodo-notready.md) | `KubeNodeNotReady`, tormentas |
| [Servicio sin endpoints](../../backend/conocimiento/runbooks/k8s-servicio-sin-endpoints.md) | `TargetDown`, selector mal escrito |
| [Despliegue atascado](../../backend/conocimiento/runbooks/k8s-rollout-atascado.md) | `KubeDeploymentRolloutStuck` |
| [Gasto anómalo o presupuesto en riesgo](../../backend/conocimiento/runbooks/costos-anomalia-y-presupuesto.md) | Alertas de costo, export vacío |
| [Hallazgo de seguridad crítico o alto](../../backend/conocimiento/runbooks/riesgo-hallazgo-critico.md) | Triaje, corregir, asumir, aceptar, excepción |
| [Job diario o chequeo HTTP caído](../../backend/conocimiento/runbooks/plataforma-recolector-y-chequeos.md) | Collector, chequeos, agente sin reportar |

Para agregar uno: un archivo Markdown con un `# Título` y secciones `##` (cada sección es un fragmento del índice). Al desplegar, el job diario lo indexa; o *Plataforma → IA → Base de conocimiento → Reindexar*. Conviene sumar una pregunta a [`eval/recuperacion.py`](../../backend/eval/recuperacion.py) que deba encontrarlo.

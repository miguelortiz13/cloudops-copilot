# Runbook: servicio sin endpoints (TargetDown)

Alertas: `TargetDown`, `KubeServiceWithoutEndpoints`, errores 503 de quien llama al servicio. Los pods pueden estar sanos: el servicio no los encuentra.

## Síntomas

- `kubectl get endpoints <servicio> -n <ns>` sale vacío aunque los pods estén `Running` y listos.
- Eventos `FailedToUpdateEndpoint` o `No pods match selector app=...`.
- En la foto del clúster, el servicio aparece con 0 endpoints.

## Diagnóstico

1. Comparar el selector del servicio con las etiquetas de los pods:
   `kubectl get svc <servicio> -n <ns> -o jsonpath='{.spec.selector}'` y `kubectl get pods -n <ns> --show-labels`.
2. Un selector mal escrito (`app=currency-service` contra pods `app=currencyservice`) o una etiqueta que cambió en un despliegue es la causa más común.
3. Si el selector coincide, revisar que los pods estén listos: un pod que no pasa su readiness no entra en los endpoints.
4. Revisar el puerto: `targetPort` del servicio contra el puerto del contenedor.

## Resolución

- Corregir el selector del servicio o las etiquetas del Deployment en el repositorio y aplicar.
- Si es la readiness, ver por qué no pasa (log del pod, dependencia caída).

## Verificación

- `kubectl get endpoints` muestra las IPs de los pods y el objetivo vuelve a `up` en Prometheus.

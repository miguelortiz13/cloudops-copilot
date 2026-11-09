# Runbook: el job diario falla o un chequeo HTTP cae

## Job diario (collector) con error o parcial

El job corre a las 06:00 UTC y deja cada paso en *Plataforma → Estado*. Un paso `parcial` siguió con lo que pudo; uno en `error` no actualizó sus datos.

1. **La base no responde al empezar** (Azure SQL serverless pausada): el job espera hasta 4 minutos a que reanude. Si falla igual, volver a lanzarlo: `az containerapp job start -n <job> -g <grupo>`.
2. **Permisos** (`AuthorizationFailed`, `AccessDenied`): la identidad del job perdió un rol sobre una suscripción o cuenta. Revisar *Plataforma → Cuentas* y los roles de lectura (Reader, Cost Management Reader; en AWS, el rol de solo lectura).
3. **Límite de tasa** (`429`, `Throttling`): el paso queda parcial y se recupera en la próxima corrida.
4. **Costos atrasados**: revisar el export de costos (ver el runbook de gasto anómalo, *export vacío*).
5. Los avisos de la corrida salen al final: si un paso falló, el aviso diario lo dice.

## Chequeo HTTP caído

Los chequeos de *Plataforma → Ajustes → Chequeos* los revisa k8s-watch cada 10 minutos; dos fallas seguidas abren un incidente.

1. Abrir la URL desde fuera: ¿responde? ¿qué código?
2. Si responde bien desde fuera, revisar DNS, certificado vencido o un WAF que bloquea al chequeo.
3. Si no responde: revisar el servicio detrás (el pod, la app o la Container App) y sus despliegues recientes.
4. Cuando vuelve a responder, el incidente se resuelve solo.

## Agente de Kubernetes sin reportar

Si un clúster aparece con foto vieja en *Activos → Kubernetes*, el agente dejó de enviar: revisar su pod (`kubectl get pods -n cloudops`), su log y que el secreto `cloudops-agent` (token de ingesta) siga vigente.

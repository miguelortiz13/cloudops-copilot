# Guía: cómo se hace en el panel de CloudOps Copilot

El panel se organiza en seis dominios: Inicio, Activos, Costos, Riesgo, Operación y Plataforma. Leer requiere el rol Lector; gestionar (estados, silencios, excepciones), Operador; ajustes, tokens y auditoría, Administrador.

## Ver lo que me toca

*Inicio → Resumen* muestra **Mis pendientes** (lo asignado a mí, lo crítico sin responsable y lo que vence pronto, ordenado por urgencia) y **Qué cambió** desde mi última visita.

## Gestionar un incidente

En *Operación → Incidentes* se abre el incidente y se usan los botones **Reconocer**, **En curso**, **Cerrar…** (con motivo: solucionado, falso positivo, ruido o duplicado) y **Reabrir**. Quien reconoce un incidente sin responsable queda como responsable. **Volver a diagnosticar** pide un diagnóstico nuevo al agente. Después de resolverlo conviene marcar si el diagnóstico fue correcto o incorrecto: esas marcas miden al agente y los incidentes correctos alimentan la base de conocimiento. En un incidente cerrado, la sección *Post-mortem (borrador)* tiene **Redactar** (o **Rehacer**): el agente escribe un borrador sin culpables para revisar antes de compartir.

## Silenciar alertas

**Silenciar similares…** desde un incidente, o *Operación → Silencios → Nuevo silencio*. Un silencio necesita al menos clúster, namespace, alerta u objeto (no se puede silenciar todo) y vence solo (de 1 hora a 30 días). Lo silenciado no abre incidentes, no se diagnostica y no se avisa. El campo *alerta* también calla un tipo de aviso entero, por ejemplo `resumen_semanal` o `atencion_diaria`.

## Gestionar hallazgos y riesgos

En *Riesgo → Hallazgos* un hallazgo se **asume** (**Asumir**: responsable y fecha objetivo) o se acepta (**Aceptar el riesgo**: justificación y vencimiento). Se resuelve solo cuando la regla deja de fallar. En *Riesgo → Cumplimiento*, **Exceptuar este control…** crea una excepción con justificación y vencimiento (hasta un año), y **Revocar la excepción** la quita. La clasificación de un recurso se cambia en *Riesgo → Clasificación* con **Cambiar clasificación** o **Restaurar la automática**.

## Alertas de costo y ahorro

*Costos → Alertas de costo*: **Reconocer**, **Resolver**, **Descartar** o **Reabrir**, con responsable y nota; **Explicar con IA** pide el porqué del gasto. *Costos → Ahorro* registra una baja aplicada y la verifica sola cuando el recurso desaparece del inventario.

## Ajustes

*Plataforma → Ajustes* tiene una sección por dominio (incidentes, gobierno, costos, IA, avisos, riesgo, chequeos) y ajustes por clúster. Cada cambio queda en el historial con quién lo hizo y se puede deshacer. Ahí se configuran los presupuestos, las tags obligatorias, qué severidades se diagnostican y avisan, el precio del modelo, los chequeos HTTP y el modo del motor de avisos.

## Avisos al canal

*Operación → Avisos* muestra todo lo que se publicó (o se habría publicado) en Discord, Slack o Teams. En modo `registro` se envía todo y solo se anota lo que se habría silenciado o descartado; en modo `activo` se aplican silencios, severidad mínima por dominio y duplicados.

## IA y acceso MCP

*Plataforma → IA* muestra las llamadas al modelo, el costo, la latencia, las trazas y los evals. En **Acceso MCP** un administrador emite un token de solo lectura (7, 30 o 90 días) para conectar Claude Code u otro agente; el comando `claude mcp add` aparece al emitirlo, el token se muestra una sola vez y se puede revocar. La base de conocimiento (runbooks, incidentes resueltos, catálogo de controles) se reindexa cada día y con el botón de reindexar.

## Reportes y cuentas

*Plataforma → Reportes* genera el reporte ejecutivo mensual en PDF. *Plataforma → Cuentas* lista las suscripciones, cuentas de AWS y clústeres conectados; *Plataforma → Auditoría* registra quién hizo qué.

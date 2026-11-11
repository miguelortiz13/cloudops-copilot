# Guía: cómo se hace en el panel de CloudOps Copilot

El panel se organiza en seis dominios: Inicio, Activos, Costos, Riesgo, Operación y Plataforma. Leer requiere el rol Lector; gestionar (estados, silencios, excepciones), Operador; ajustes, tokens y auditoría, Administrador.

## Ver lo que me toca

*Inicio → Resumen* muestra **Mis pendientes** (lo asignado a mí, lo crítico sin responsable y lo que vence pronto, ordenado por urgencia; **Por dónde empiezo** pide a la IA las 1 a 3 primeras acciones), **Qué cambió** desde mi última visita y **Valor de la operación**: tiempo hasta reconocer y hasta resolver, % de ruido, % de diagnósticos correctos y marcados, hallazgos graves resueltos, ahorro realizado y evals de la IA, de la última semana cerrada contra la anterior.

## Gestionar un incidente

En *Operación → Incidentes* se abre el incidente y se usan los botones **Reconocer**, **En curso**, **Cerrar…** (con motivo: solucionado, falso positivo, ruido o duplicado) y **Reabrir**. Quien reconoce un incidente sin responsable queda como responsable. **Volver a diagnosticar** pide un diagnóstico nuevo al agente. Después de resolverlo conviene marcar si el diagnóstico fue correcto o incorrecto: esas marcas miden al agente y los incidentes correctos alimentan la base de conocimiento. En un incidente cerrado, la sección *Post-mortem (borrador)* tiene **Redactar** (o **Rehacer**): el agente escribe un borrador sin culpables para revisar antes de compartir.

## Acciones de seguimiento y cierre del ciclo

En un incidente con post-mortem, **Crear desde el post-mortem** convierte las viñetas de *Acciones* en tareas con responsable; también se agregan a mano y se marcan como hechas. Las abiertas, los diagnósticos sin marcar y las alertas cerradas como ruido varias veces (para silenciarlas) aparecen en *Mis pendientes*.

## SLOs

*Operación → SLOs* muestra, para cada URL de los chequeos HTTP, su disponibilidad contra el objetivo (por defecto 99,5 % en 28 días), el presupuesto de error que queda y su quema. Si se gasta muy rápido (14,4× en 1 hora y 6× en 6 horas) se abre un incidente `SLOBurnRate`. El objetivo y la ventana se cambian en *Plataforma → Ajustes → Chequeos HTTP*.

## Silenciar alertas

**Silenciar similares…** desde un incidente, o *Operación → Silencios → Nuevo silencio*. Un silencio necesita al menos clúster, namespace, alerta u objeto (no se puede silenciar todo) y vence solo (de 1 hora a 30 días). Lo silenciado no abre incidentes, no se diagnostica y no se avisa. El campo *alerta* también calla un tipo de aviso entero, por ejemplo `resumen_semanal` o `atencion_diaria`.

## Gestionar hallazgos y riesgos

En *Riesgo → Hallazgos* un hallazgo se **asume** (**Asumir**: responsable y fecha objetivo) o se acepta (**Aceptar el riesgo**: justificación y vencimiento). Se resuelve solo cuando la regla deja de fallar. En *Riesgo → Cumplimiento*, **Exceptuar este control…** crea una excepción con justificación y vencimiento (hasta un año), y **Revocar la excepción** la quita. La clasificación de un recurso se cambia en *Riesgo → Clasificación* con **Cambiar clasificación** o **Restaurar la automática**.

## Alertas de costo y ahorro

*Costos → Alertas de costo*: **Reconocer**, **Resolver**, **Descartar** o **Reabrir**, con responsable y nota; **Explicar con IA** pide el porqué del gasto. *Costos → Ahorro* registra una baja aplicada y la verifica sola cuando el recurso desaparece del inventario.

## Asignar responsables automáticamente

En *Plataforma → Ajustes → Asignación* se escriben reglas `campo:valor=responsable` (campo: cluster, namespace o alerta), por ejemplo `namespace:boutique=ana@contoso.com`. Cada incidente nuevo sin responsable toma el de la primera regla que coincide. Los hallazgos de recursos con tu correo en la tag `Owner` aparecen en tus pendientes.

## Ajustes

*Plataforma → Ajustes* tiene una sección por dominio (incidentes, gobierno, costos, IA, avisos, riesgo, chequeos) y ajustes por clúster. Cada cambio queda en el historial con quién lo hizo y se puede deshacer. Ahí se configuran los presupuestos, las tags obligatorias, qué severidades se diagnostican y avisan, el precio del modelo, los chequeos HTTP y el modo del motor de avisos.

## Avisos al canal

*Operación → Avisos* muestra todo lo que se publicó (o se habría publicado) en Discord, Slack o Teams. En modo `registro` se envía todo y solo se anota lo que se habría silenciado o descartado; en modo `activo` se aplican silencios, severidad mínima por dominio y duplicados.

## IA y acceso MCP

*Plataforma → IA* muestra las llamadas al modelo, el costo, la latencia, las trazas y los evals. En **Acceso MCP** un administrador emite un token de solo lectura (7, 30 o 90 días) para conectar Claude Code u otro agente; el comando `claude mcp add` aparece al emitirlo, el token se muestra una sola vez y se puede revocar. La base de conocimiento (runbooks, incidentes resueltos, catálogo de controles) se reindexa cada día y con el botón de reindexar.

## Reportes y cuentas

*Plataforma → Reportes* genera el reporte ejecutivo mensual en PDF. *Plataforma → Cuentas* lista las suscripciones, cuentas de AWS y clústeres conectados; *Plataforma → Auditoría* registra quién hizo qué.

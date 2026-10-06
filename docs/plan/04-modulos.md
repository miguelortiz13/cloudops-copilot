# 4. Plan por módulo

Cada módulo se describe igual: **estado hoy**, **brechas**, **mejoras** (con el valor que aportan, el esfuerzo y la fase de la [hoja de ruta](07-hoja-de-ruta.md)) y **criterios de aceptación** verificables.

Esfuerzo: **S** = hasta 2 días · **M** = hasta 1 semana · **L** = 2 semanas o más (estimación para una persona).

Índice: [Resumen](#resumen) · [Inventario](#inventario-y-gobernanza) · [Costos](#costos-finops) · [Seguridad](#seguridad-secops) · [IaC](#iac-y-terraform) · [Kubernetes](#kubernetes) · [Cumplimiento](#cumplimiento) · [Agentes de IA](#agentes-de-ia) · [Reportes e integraciones](#reportes-e-integraciones) · [Módulos nuevos](#módulos-nuevos)

---

## Resumen

**Hoy.** Portada con gasto de 30 días, cumplimiento de tags, hallazgos y cobertura de Terraform, con enlaces a cada módulo. Todo en vivo y solo de Azure.

**Brechas.** No dice qué cambió desde ayer ni qué requiere atención hoy. No compara nubes.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Bloque "Qué cambió" (últimas 24 h y 7 días): recursos nuevos, hallazgos abiertos y cerrados, variación de gasto | Convierte la portada en el parte diario del equipo | M | 1 |
| Desglose por proveedor en cada KPI (Azure / AWS) | Primera vista de valor multinube | S | 2 |
| Puntaje de salud por cuenta (costo, seguridad, gobernanza, IaC) con su tendencia | Ordena dónde mirar primero en organizaciones con muchas cuentas | M | 3 |
| Bandeja "Mis pendientes": hallazgos asignados al usuario y aceptaciones por vencer | Lleva el ciclo de vida a la primera pantalla | S | 3 |

**Aceptación.** La portada carga en menos de 1 s desde la base de datos; cada número indica la antigüedad del dato y enlaza a su detalle filtrado.

---

## Inventario y gobernanza

**Hoy.** Inventario en vivo con Resource Graph, KPIs agregados, matriz de tags configurable, regla de Shadow IT de cuatro señales, histórico diario (JSONL) y exportación a CSV.

**Brechas.**
- Sin historia de recursos: no se sabe cuándo apareció o desapareció algo.
- El histórico de KPIs solo se escribe cuando alguien abre la página.
- Las claves de custodio y de evidencia IaC están en el código, no en la configuración.
- No distingue ambientes por convención de nombres, solo por tag.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Recolector de inventario con `first_seen` / `last_seen` por recurso | Altas y bajas en el tiempo; base de todo el histórico | M | 1 |
| Claves de custodio, evidencia IaC y valores inválidos configurables | Adoptable por cualquier organización sin tocar código | S | 1 |
| Validación de **valores** de tags contra vocabularios cerrados (`Environment ∈ {prod, qa, dev}`) | Detecta `Prod`, `prd` y `produccion` como el mismo problema de showback | M | 1 |
| Validación de nombres contra la convención (patrón configurable) | Señal adicional de recursos creados a mano | S | 3 |
| Inventario AWS con Resource Explorer y tipos canónicos | Una sola vista de inventario multinube | L | 2 |
| Vista de **ciclo de vida**: recursos temporales con fecha de expiración vencida | Evita recursos olvidados que siguen cobrando | S | 3 |
| Detección de variantes de claves de tag (`project` / `Project`) | Higiene de tags, crítica en AWS | S | 2 |

**Aceptación.** Un recurso borrado en Azure o AWS aparece como baja con fecha en la siguiente recolección; la prueba de integración KQL vs. memoria sigue en verde; el mismo filtro de tags devuelve resultados de ambas nubes.

---

## Costos (FinOps)

**Hoy.** Visión general (30 días frente a los 30 anteriores, mes en curso, proyección, desgloses, ranking) y optimización (recursos sin uso, right-sizing, reservas, presupuestos, anomalías), sobre Cost Management con caché persistente.

**Brechas.**
- Solo 30 días por recurso y 60 de serie: no hay comparación mes a mes ni año.
- La API de consulta de Azure responde 429 con facilidad y no hay respaldo cuando falla la serie diaria.
- La anomalía es una comparación simple de promedios.
- El ahorro "aprobado" y "realizado" no se mide: no hay forma de saber si una recomendación se aplicó.
- Sin costo unitario (por cliente, producto o transacción).

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| **Costos en la base de datos en formato FOCUS**, alimentados por exports (Azure Cost Management exports y AWS CUR 2.0) | Meses de historia, sin 429, base común multinube | L | 1-2 |
| Selector de periodo (7 / 30 / 90 días, mes actual, mes anterior, año) y comparación mes a mes | La pregunta más común de FinOps | M | 1 |
| Pronóstico con estacionalidad semanal y banda de confianza | Una proyección lineal sobre 7 días engaña en cuentas con patrón semanal | M | 3 |
| Anomalías estadísticas por servicio y por cuenta, con evento y alerta | Detectar el pico el mismo día, no al mes siguiente | M | 3 |
| **Seguimiento de ahorro**: al cerrar una recomendación se compara el gasto antes y después | Demuestra el valor de la plataforma en dinero | M | 3 |
| Presupuestos con alertas al 80 % y 100 % del consumo y del pronóstico | Control preventivo | S | 3 |
| **Costo unitario**: gasto dividido por una métrica de negocio que se carga por API (usuarios, pedidos) | Pasa de "cuánto gastamos" a "cuánto cuesta servir a un cliente" | M | 4 |
| Showback por tag con reglas de reparto del gasto compartido (proporcional o fijo) | Chargeback que finanzas puede usar | M | 4 |
| Detección de compromisos: cobertura y uso de reservas y Savings Plans en ambas nubes | Las reservas mal aprovechadas son gasto perdido | M | 3 |
| Recursos sin uso en AWS (EBS, EIP, ENI, snapshots, LB vacíos, NAT ociosos) | Paridad de ahorro con Azure | M | 2 |

**Aceptación.** El gasto de un mes cerrado coincide con la factura del proveedor (±1 %); el panel muestra 12 meses de historia; una anomalía sembrada en una cuenta de prueba genera un evento en menos de 24 h.

---

## Seguridad (SecOps)

**Hoy.** Siete reglas propias sobre Resource Graph, severidad por alcanzabilidad, priorización por gasto expuesto y lista unificada de hallazgos.

**Brechas.**
- Los hallazgos no tienen estado: no se pueden asumir, aceptar con fecha de vencimiento ni marcar resueltos.
- Siete reglas cubren poco frente a un benchmark como CIS.
- No integra los hallazgos nativos de Defender for Cloud ni de Security Hub.
- La identidad (permisos excesivos, cuentas sin MFA, llaves antiguas) no se evalúa.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| **Ciclo de vida de hallazgos**: abierto → asumido (dueño, fecha) → resuelto, o aceptado con justificación y vencimiento | Es la diferencia entre un reporte y un proceso | L | 1 |
| Catálogo de reglas con mapeo a controles CIS e ISO 27001 | Las reglas hablan el idioma de una auditoría | M | 1 |
| Importar hallazgos de Defender for Cloud y Security Hub al modelo canónico | Cobertura amplia sin reescribir cientos de reglas | M | 2-3 |
| Reglas de identidad: roles privilegiados permanentes, llaves de más de 90 días, raíz sin MFA (AWS) | La identidad es el vector más común en nube | M | 3 |
| Tiempo medio de remediación (MTTR) por severidad y por equipo | Métrica de mejora real | S | 3 |
| Exposición por **ruta**: recurso público + secreto accesible + rol con privilegios | Prioriza combinaciones peligrosas, no hallazgos aislados | L | 4 |
| Reglas AWS equivalentes ([ver tabla](03-multicloud.md#reglas-de-seguridad-equivalentes)) | Paridad multinube | M | 2 |

**Aceptación.** Un hallazgo corregido en la nube se marca resuelto en la siguiente recolección con su fecha; una aceptación vencida reabre el hallazgo y notifica al dueño; cada regla indica sus controles CIS e ISO.

---

## IaC y Terraform

**Hoy.** Cobertura real leída de los estados (varias cuentas), ids obsoletos, creaciones manuales con identidad y generador de HCL (plantillas para VM y Storage, o Gemini).

**Brechas.**
- El generador solo tiene plantillas para dos tipos; el resto depende del modelo de IA.
- El HCL termina en un modal: no llega a un repositorio.
- No detecta **drift**: un recurso en el estado cuya configuración real cambió fuera de Terraform.
- La ventana de "quién lo creó" es de ~14 días en Azure y no se guarda.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Guardar la actividad (`resourcechanges`, CloudTrail) en la base de datos | Evidencia de creación manual que no caduca | S | 1 |
| **PR de remediación**: publicar el HCL con bloque `import` en el repositorio de infraestructura (GitHub App) | Cierra el ciclo hallazgo → código revisado | M | 3 |
| Generación con `terraform plan -generate-config-out` cuando haya runner disponible | HCL exacto en lugar de plantillas aproximadas | M | 3 |
| Detección de drift comparando atributos clave del estado con la configuración real | Detecta cambios hechos en el portal sobre recursos codificados | L | 4 |
| Estados en S3 con resolución de ARN ([ver detalle](03-multicloud.md#estados-de-terraform-en-s3)) | Cobertura de IaC multinube | M | 2 |
| Soporte de estados de OpenTofu y de Terraform Cloud / HCP (por API) | Muchas organizaciones no guardan el estado en un bucket | M | 4 |
| Cobertura por equipo o proyecto, con tendencia | Mide la adopción de IaC como objetivo del equipo | S | 3 |

**Aceptación.** Un recurso creado a mano genera, con un clic, un PR que pasa `terraform plan` sin cambios; la cobertura de IaC se muestra por nube y por proyecto con 90 días de historia.

---

## Kubernetes

**Hoy.** Un clúster AKS configurado por variables; overview, incidencias, logs y chat SRE vía Run Command, con comandos validados. No tiene pantalla propia en el panel nuevo, solo el agente.

**Brechas.** Un solo clúster; sin pantalla; sin historia de incidentes; Run Command es lento (segundos por comando) y no sirve para una flota.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Página de Kubernetes con inventario de clústeres (versión, nodos, pools, fin de soporte) | Visibilidad de flota y de deuda de versiones | M | 2 |
| Varios clústeres AKS y EKS, descubiertos por el inventario | Escala de un clúster a una flota | M | 2 |
| Costo por namespace (Kubecost / OpenCost como fuente opcional) | Showback dentro del clúster, donde está la mayor parte del gasto | L | 4 |
| Hallazgos de Kubernetes al catálogo: pods privilegiados, imágenes `latest`, sin límites de recursos | Seguridad y eficiencia del clúster en el mismo flujo de hallazgos | M | 3 |
| Agente ligero de solo lectura dentro del clúster (alternativa a Run Command) | Clústeres privados y respuesta inmediata | L | 4 |

**Aceptación.** El panel lista todos los clústeres de ambas nubes con su versión y la fecha de fin de soporte; las incidencias quedan registradas con hora de inicio y fin.

---

## Cumplimiento

**Hoy.** Clasificación ISO 27001 (C-I-D, criticidad) calculada por el pipeline y leída de la hoja 12 del Excel.

**Brechas.** Depende de un Excel que se regenera a mano; no hay evidencia por control; un solo marco.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Mover la clasificación de activos a la base de datos (sin Excel) | Clasificación siempre al día y consultable | M | 1 |
| Vista por **control** (CIS, ISO 27001 Anexo A, SOC 2): reglas que lo evidencian, estado y hallazgos abiertos | Lo que pide un auditor | L | 3 |
| Paquete de evidencia exportable (PDF/CSV con fecha, alcance y resultados por control) | Ahorra días de preparación de auditoría | M | 4 |
| Excepciones documentadas por control, enlazadas a hallazgos aceptados | Trazabilidad de decisiones de riesgo | S | 3 |

**Aceptación.** Para cada control se puede ver qué reglas lo cubren, su estado a una fecha y exportarlo; el Excel deja de ser necesario para ISO.

---

## Agentes de IA

**Hoy.** Cuatro agentes (inventario, costos, seguridad, Kubernetes) con Gemini o motor de reglas; contexto precargado y acotado.

**Brechas.** SDK de Gemini en desuso; sin uso de herramientas; las respuestas se limitan a lo que se precargó; no hay evaluación de calidad.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Interfaz de proveedor de LLM (Gemini con `google-genai`, Azure OpenAI, Claude) | Elegir modelo por costo y calidad sin reescribir | M | 1 |
| **Uso de herramientas**: el modelo llama funciones tipadas del API con los permisos del usuario | Responde cualquier pregunta sobre los datos, no solo lo precargado | L | 3 |
| Respuestas con citas: cada cifra enlaza a la vista que la respalda | Confianza y verificación | M | 3 |
| Conjunto de evaluación: preguntas con respuesta verificable contra el tenant de prueba, en CI | Detectar regresiones del agente | M | 3 |
| Agente proactivo: resumen semanal generado y enviado a Teams | Valor sin que nadie tenga que preguntar | S | 3 |
| Límite de uso y registro de consultas por usuario | Control de costo y auditoría | S | 1 |

**Aceptación.** Las preguntas del conjunto de evaluación se responden con al menos un 90 % de exactitud; cada respuesta numérica coincide con el panel.

---

## Reportes e integraciones

**Hoy.** Descarga del Excel maestro y snapshots; prueba manual de webhook de Teams; bot de Teams como paso manual.

| Mejora | Valor | Esfuerzo | Fase |
|---|---|---|---|
| Notificaciones por eventos (Teams, Slack, correo) con reglas de enrutamiento por severidad, cuenta o proyecto | La plataforma avisa en lugar de esperar | M | 3 |
| Reporte ejecutivo mensual en PDF (costo, seguridad, gobernanza, IaC, tendencias) | Lo que se lleva a una reunión de dirección | M | 3 |
| Integración con tickets (Jira, Azure Boards, GitHub Issues) desde un hallazgo | Encaja con el proceso que el equipo ya usa | M | 4 |
| Bot de Teams con credencial federada, sin secreto | Recupera el canal conversacional sin llaves | M | 3 |
| API pública documentada con tokens de servicio | Integrar la plataforma en otros procesos | S | 4 |
| Retirar el pipeline de Excel una vez que la base de datos lo reemplace | Menos piezas que mantener | S | 2 |

**Aceptación.** Un hallazgo crítico nuevo llega a Teams al terminar la siguiente ventana de recolección (menos de 26 h, o al momento si se evaluó bajo demanda) con enlace al detalle, y no se repite mientras siga abierto.

---

## Módulos nuevos

Tres módulos que hoy no existen y que completan el propósito de la plataforma.

### Hallazgos y remediación (centro de acción)

Una bandeja única con **todo lo que requiere acción**, venga de donde venga: seguridad, costos (recursos sin uso, anomalías), gobernanza (tags, nombres) e IaC (recursos sin codificar, drift).

- Estados: abierto, asumido, en remediación (PR abierto), resuelto, aceptado hasta una fecha.
- Asignación por regla: un hallazgo de un recurso con tag `Owner` se asigna solo a esa persona o equipo.
- Acciones: preguntar al agente, generar PR, crear ticket, aceptar con justificación.
- Métricas: abiertos por antigüedad, MTTR, ahorro realizado, deuda por equipo.

Es el módulo que convierte la plataforma en un proceso. Fase 1 (modelo y estados) y fase 3 (acciones).

### Políticas como código

Estado de las políticas preventivas de cada nube, junto a lo que la plataforma detecta después:

- Azure Policy: asignaciones, cumplimiento y exenciones.
- AWS: Service Control Policies, políticas de tags de Organizations, Config Rules.
- Brecha entre política y realidad: "la política exige `Environment`, pero el 10 % de los recursos no lo tiene porque la política está en modo auditoría".
- Generación de la política sugerida (Terraform) para que una regla detectiva pase a ser preventiva.

Valor: cierra el ciclo **detectar → prevenir**. Fase 4.

### Administración de la plataforma

Hoy la configuración vive en variables de entorno. Hace falta una pantalla para operar la plataforma:

- Nubes y cuentas conectadas, con su estado de autenticación y permisos efectivos.
- Recolectores: última ejecución, duración, errores y botón de reejecución.
- Usuarios y roles (lector, operador, administrador).
- Configuración de gobernanza: tags obligatorias, vocabularios, claves de custodio, convención de nombres.
- Destinos de notificación y reglas de enrutamiento.
- Registro de auditoría.

Fase 1 (recolectores y cuentas) y fase 3 (resto).

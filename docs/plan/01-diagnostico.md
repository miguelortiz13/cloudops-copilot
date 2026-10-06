# 1. Diagnóstico

Estado de la plataforma en la versión 2.3.0, medido sobre el código y sobre el despliegue real en un tenant personal (3 suscripciones, ~31 recursos, ~7 USD/mes de gasto).

## Lo que ya tiene valor

| Fortaleza | Por qué importa |
|---|---|
| Reglas de dominio definidas una sola vez (`governance.py`, `kql.py`, `pricing.py`) | Panel, reportes y chat dan las mismas cifras; es la base para añadir proveedores sin multiplicar reglas |
| Procedencia de cada cifra (`basis`, `coverage`) | Una herramienta de costos que mezcla factura con estimación sin decirlo no sirve para decidir |
| Cobertura de IaC leída de los estados, no de tags | Diferenció un 8 % "por tags" de un 1,1 % real en un tenant de producción |
| KPIs agregados en Resource Graph | El tiempo de respuesta no crece con el tamaño del tenant |
| Identidad administrada y Entra ID, despliegue a costo casi cero | Seguro y barato de operar |
| 97 pruebas unitarias y una prueba de integración KQL vs. memoria | Las reglas se pueden cambiar con red de seguridad |

## Lo que limita el crecimiento

### Arquitectura

| # | Limitación | Evidencia en el código | Consecuencia |
|---|---|---|---|
| A1 | **Azure está en todas partes** | `cost_service.subscription_of()` asume ids `/subscriptions/...`; los servicios reciben `subscription_ids`; las consultas son KQL de Resource Graph | Añadir AWS hoy significaría duplicar cada servicio |
| A2 | **Sin persistencia de dominio** | Todo se calcula por petición; las cachés son JSON en un File Share; el histórico es un JSONL que solo se escribe cuando alguien abre el resumen | No hay tendencias de costo más allá de 60 días, ni historia de hallazgos, ni evidencia para auditoría |
| A3 | **El trabajo pesado corre dentro del API** | La precarga de costos es un hilo; el pipeline de inventario se lanza con `subprocess` desde un endpoint | Con escala a cero el contenedor se apaga y el hilo o el pipeline mueren a mitad de camino |
| A4 | **Agente monolítico** | `agents/azure_agent.py` (~1.500 líneas) mezcla cliente de Resource Graph, estadísticas, chat, motor de reglas y construcción de prompts | Difícil de probar y de extender a otra nube |
| A5 | **Contenedor de servicios posicional** | `get_services()[10]` | Un servicio nuevo obliga a contar posiciones; un error de índice compila |
| A6 | **El Excel es la base de datos de las revisiones manuales** | 11 scripts con `openpyxl`; ISO 27001 se lee de la hoja 12 | No es consultable, no es multiusuario y se corrompe con escrituras concurrentes |

### Producto

| # | Limitación | Consecuencia |
|---|---|---|
| P1 | Los hallazgos no tienen dueño ni estado (abierto, aceptado, resuelto) | El panel informa pero no se puede medir si algo mejora |
| P2 | No hay alertas: hay que entrar al panel a mirar | Una anomalía de costo de un viernes se descubre el lunes |
| P3 | Las remediaciones terminan en un bloque de texto | No hay camino de "hallazgo → PR revisado → cerrado" |
| P4 | Costos limitados a 30/60 días y a la API de consulta (con 429 frecuentes) | No hay comparación mensual, presupuesto anual ni pronóstico serio |
| P5 | Seguridad con 7 reglas propias | Cobertura limitada frente a benchmarks como CIS; no aprovecha Defender ni Security Hub |
| P6 | Kubernetes: un solo clúster fijado por variables | No escala a una flota |
| P7 | Agentes sin herramientas: el contexto se arma completo antes de preguntar | Respuestas limitadas a lo que se precargó; el SDK de Gemini está en desuso |

### Operación

| # | Limitación | Consecuencia |
|---|---|---|
| O1 | Despliegue manual desde un portátil | Sin trazabilidad de qué versión está en producción ni posibilidad de revertir con un clic |
| O2 | Un solo ambiente | Los cambios se prueban en producción |
| O3 | Sin observabilidad (sin Log Analytics por costo) | Un fallo de la precarga o un 429 sostenido solo se ve leyendo logs en vivo |
| O4 | Una sola autorización: entrar o no entrar | Cualquier usuario asignado puede lanzar el pipeline o usar el agente de Kubernetes |
| O5 | Sin auditoría de acciones | No se puede responder quién lanzó qué |
| O6 | Frontend sin pruebas automatizadas | El rediseño se verificó con capturas manuales |
| O7 | El ACR se comparte con otro proyecto | Borrar ese proyecto rompe el despliegue |

## Conclusión del diagnóstico

Las reglas y la honestidad de las cifras son sólidas. Lo que falta es **estructura**: un modelo de datos independiente del proveedor, un lugar donde persistir y procesos que trabajen fuera del ciclo de la petición. Sin eso, cada mejora de producto (alertas, ciclo de vida, multinube) tendría que construirse contra Azure y en memoria. Por eso la [hoja de ruta](07-hoja-de-ruta.md) empieza por los fundamentos antes de sumar AWS.

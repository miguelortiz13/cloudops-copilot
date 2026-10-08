# 0007 · Almacén de datos y recolectores programados

**Estado:** aceptada e implementada: base, esquema y recolector diario (fase 1 del [plan de evolución](../plan/README.md)).

## Contexto

Todo se calcula por petición. La historia se limita a un JSONL que solo se escribe cuando alguien abre el resumen; la actividad de Azure se pierde a los ~14 días; los hallazgos no tienen estado; el trabajo pesado (precarga de costos, pipeline de Excel) corre dentro del API, y con escala a cero el contenedor se apaga a mitad del trabajo.

## Decisión

1. **Base de datos relacional** con el modelo canónico, accedida con SQLAlchemy y migraciones de Alembic. Se usa Azure SQL Database con la **oferta gratuita** (serverless, 100.000 vCore-segundos y 32 GB al mes); el código no usa SQL propietario para poder pasar a PostgreSQL por configuración.
2. **Recolectores en un Container Apps Job diario** que lee las nubes y escribe en la base; idempotentes y con registro de ejecución.
3. El API lee de la base por defecto. La vista de inventario y la evaluación de hallazgos bajo demanda siguen consultando en vivo.

## Por qué una ventana diaria

La base serverless consume mientras está despierta. Un recolector horario la mantendría activa todo el mes (~1,3 millones de vCore-segundos, 13 veces el cupo); una ventana diaria más el uso normal queda en ~90.000. El cálculo está en [infraestructura](../plan/05-infraestructura.md#presupuesto-de-cómputo-de-la-base-de-datos).

## Consecuencias

- Historia de costos, hallazgos, actividad y KPIs sin depender de que alguien abra el panel.
- Sin límites de tasa en el camino de la petición.
- Los datos de la base tienen hasta un día de antigüedad, y el panel debe mostrarlo.
- El Excel deja de ser la fuente de las revisiones manuales y de ISO.
- Aparece un componente con estado que necesita backups, migraciones y monitoreo.

## Notas de implementación

- **Driver**: `mssql-python` (el driver oficial de Microsoft, con el ODBC incluido) y el dialecto `mssql+mssqlpython` de SQLAlchemy 2.1. Autenticación `ActiveDirectoryMSI` con la identidad del API y `ActiveDirectoryDefault` (sesión de `az login`) en desarrollo.
- **Oferta gratuita**: `azurerm` no expone `useFreeLimit` ni `freeLimitExhaustionBehavior`, así que la base se declara con `azapi`. Con `AutoPause` la oferta solo admite el retardo de pausa por defecto, 60 minutos.
- **Región**: centralus. eastus2 y eastus rechazan servidores SQL nuevos en suscripciones de pago por uso.
- **Pruebas**: el mismo esquema corre en SQLite; `alembic check` en las pruebas detecta un modelo cambiado sin migración.
- **Recolectores** (`app/collectors/`): inventario, costos, hallazgos y KPIs reutilizan los servicios del panel. Usan el modo estricto de `AzureClient` (`raise_errors=True`): una consulta fallida aborta o deja el resultado como parcial, y nunca se interpreta como "sin resultados". Si no, un corte de Resource Graph marcaría como resueltos hallazgos que siguen abiertos.
- **Lecturas del panel** (`app/readmodel`): el último paso del recolector precalcula las vistas por defecto y las deja en `DATA_DIR/readmodel`, que es el File Share montado por el job y por el API. Las vistas valen hasta la siguiente recolección (07:00 UTC), así que leerlas no despierta la base. Si la base no está disponible (sin configurar o pausada por agotar el cupo), los endpoints responden 503 y el panel conserva sus vistas en vivo.
- **Carga inicial de costos**: un año (364 días; 365 superan el límite de un año de Cost Management contando el día final). Después, una ventana móvil de 7 días. "Periodo anterior completo" se calcula desde la cobertura de la recolección y no desde la primera fila con gasto, porque un día sin gasto no deja filas.

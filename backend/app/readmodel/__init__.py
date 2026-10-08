"""
Lecturas del panel desde la base, con cache en disco.

La base solo cambia una vez al dia (recolector de las 06:00 UTC) y cuando
alguien gestiona un hallazgo. Cada conexion la despierta durante una hora y
consume cupo gratuito, asi que las vistas no la consultan en cada visita:

1. El recolector, al terminar, calcula las vistas por defecto y las deja en
   `DATA_DIR/readmodel` (el File Share que tambien monta el API).
2. El API responde desde ese archivo hasta la siguiente recoleccion.
3. Solo una consulta fuera de las vistas por defecto, o un cambio de estado
   de un hallazgo, abre la base.

El presupuesto del cupo esta en docs/plan/05-infraestructura.md.
"""

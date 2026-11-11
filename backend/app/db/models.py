"""
Modelo canonico (docs/plan/02-arquitectura-objetivo.md#modelo-canónico).

Independiente de la nube: cada fila lleva `provider` y un `uid` universal
(`azure:/subscriptions/...`, `arn:aws:...`). Sin tipos propietarios: el mismo
esquema corre en Azure SQL, PostgreSQL y SQLite (pruebas).

Las fechas se guardan en UTC.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Numeric, String, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Los identificadores de recurso de Azure rara vez pasan de 300 caracteres;
# 450 es el maximo que SQL Server admite en una clave indexada (900 bytes).
UID = String(450)
# Lo que lee una persona (nombres, titulos, notas) va en Unicode: en SQL Server
# VARCHAR depende de la intercalacion y puede perder caracteres.


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Account(Base):
    """Suscripcion de Azure, cuenta de AWS o proyecto de GCP."""

    __tablename__ = "accounts"

    uid: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    native_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(Unicode(200))
    # Grupo de administracion u OU.
    parent: Mapped[Optional[str]] = mapped_column(String(200))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Resource(Base):
    __tablename__ = "resources"

    uid: Mapped[str] = mapped_column(UID, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    account_uid: Mapped[str] = mapped_column(ForeignKey("accounts.uid"), index=True)
    name: Mapped[str] = mapped_column(Unicode(260))
    # Tipo comun a todas las nubes (storage.bucket, compute.vm...) y el nativo.
    canonical_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    native_type: Mapped[str] = mapped_column(String(200))
    region: Mapped[Optional[str]] = mapped_column(String(64))
    # Grupo de recursos en Azure; vacio en nubes sin ese concepto.
    group_name: Mapped[Optional[str]] = mapped_column(Unicode(200))
    tags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    in_iac_state: Mapped[Optional[bool]]
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(320))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Un recurso que deja de aparecer se marca, no se borra: su costo y sus
    # hallazgos siguen refiriendolo.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CostDaily(Base):
    """Costo por dia y recurso, con columnas FOCUS (ADR 0008)."""

    __tablename__ = "cost_daily"
    __table_args__ = (
        UniqueConstraint("charge_date", "account_uid", "resource_uid", "service_name", "source", name="uq_cost_daily"),
        Index("ix_cost_daily_account_date", "account_uid", "charge_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    charge_date: Mapped[date] = mapped_column(Date)
    account_uid: Mapped[str] = mapped_column(String(200))
    # Vacio para cargos sin recurso (soporte, marketplace, impuestos).
    resource_uid: Mapped[str] = mapped_column(UID, default="")
    service_name: Mapped[str] = mapped_column(Unicode(200), default="")
    billed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    effective_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency: Mapped[str] = mapped_column(String(3))
    # export | query | estimate
    source: Mapped[str] = mapped_column(String(16))


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # storage.public-access
    capability: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Unicode(300))
    severity_default: Mapped[str] = mapped_column(String(16))
    # {"cis-azure-2.0.0": [{"control": "3.7", "match": "directa"}], "iso-27001-2022": [...]}
    frameworks: Mapped[dict[str, Any]] = mapped_column(default=dict)
    remediation: Mapped[Optional[str]] = mapped_column(UnicodeText)
    # Que riesgo representa y como se detecta (app/compliance/catalog.py).
    description: Mapped[Optional[str]] = mapped_column(UnicodeText)
    detection: Mapped[Optional[str]] = mapped_column(UnicodeText)
    reference_urls: Mapped[Optional[list[Any]]] = mapped_column(default=list)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("rule_id", "resource_uid", name="uq_finding_rule_resource"),
        Index("ix_findings_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("rules.id"))
    resource_uid: Mapped[str] = mapped_column(UID)
    account_uid: Mapped[str] = mapped_column(String(200), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    # abierto | asumido | aceptado | resuelto
    status: Mapped[str] = mapped_column(String(16), default="abierto")
    owner: Mapped[Optional[str]] = mapped_column(Unicode(320))
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    accepted_until: Mapped[Optional[date]] = mapped_column(Date)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AssetClassification(Base):
    """
    Clasificacion ISO 27001 de un recurso (app/compliance/classification.py).

    `method` es "automatica" (la recalcula el recolector cada dia) o "manual"
    (la fijo un operador y el recolector no la toca).
    """

    __tablename__ = "asset_classifications"

    resource_uid: Mapped[str] = mapped_column(ForeignKey("resources.uid"), primary_key=True)
    classification: Mapped[str] = mapped_column(Unicode(32))
    confidentiality: Mapped[int]
    integrity: Mapped[int]
    availability: Mapped[int]
    risk_required: Mapped[bool]
    custodian: Mapped[Optional[str]] = mapped_column(Unicode(320))
    method: Mapped[str] = mapped_column(String(16), default="automatica")
    reason: Mapped[Optional[str]] = mapped_column(UnicodeText)
    updated_by: Mapped[str] = mapped_column(Unicode(320))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingEvent(Base):
    """Historial de un hallazgo: deteccion, cambios de estado, resolucion."""

    __tablename__ = "finding_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(32))  # detectado | estado | resuelto | reabierto
    from_status: Mapped[Optional[str]] = mapped_column(String(16))
    to_status: Mapped[Optional[str]] = mapped_column(String(16))
    # Usuario o "recolector".
    actor: Mapped[str] = mapped_column(Unicode(320))
    note: Mapped[Optional[str]] = mapped_column(UnicodeText)


class KpiDaily(Base):
    __tablename__ = "kpi_daily"
    __table_args__ = (UniqueConstraint("day", "scope", "metric", name="uq_kpi_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date)
    # uid de la cuenta o "all".
    scope: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class CollectorRun(Base):
    """Cada ejecucion de un recolector: lo que muestra Administracion."""

    __tablename__ = "collector_runs"
    __table_args__ = (Index("ix_collector_runs_collector_started", "collector", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    collector: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # en_curso | ok | parcial | error
    items: Mapped[int] = mapped_column(default=0)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[Optional[str]] = mapped_column(UnicodeText)


class AuditLog(Base):
    """Quien hizo que: toda accion que cambia algo o actua sobre la nube."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_at", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(Unicode(320))
    actor_oid: Mapped[Optional[str]] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))  # hallazgo.estado, k8s.chat...
    target: Mapped[Optional[str]] = mapped_column(Unicode(450))
    outcome: Mapped[str] = mapped_column(String(16))  # ok | error
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Incident(Base):
    """
    Un incidente: alertas de una fuente agrupadas (mismo grupo de Alertmanager)
    y su diagnóstico por el agente (app/ai/incidentes.py, plan 09 etapa B).
    """

    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_key_status", "key", "status"), Index("ix_incidents_opened", "opened_at"))

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Fuente y grupo: una tormenta de alertas del mismo grupo es un solo incidente.
    key: Mapped[str] = mapped_column(Unicode(450))
    source: Mapped[str] = mapped_column(String(32))
    cluster: Mapped[Optional[str]] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Unicode(300))
    severity: Mapped[str] = mapped_column(String(16))  # critica | alta | media
    status: Mapped[str] = mapped_column(String(16))  # abierto | resuelto
    alerts: Mapped[list[Any]] = mapped_column(default=list)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_alert_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # diagnosticando | listo | sin_modelo | error | limite
    diagnosis_status: Mapped[str] = mapped_column(String(16), default="diagnosticando")
    diagnosis: Mapped[Optional[str]] = mapped_column(UnicodeText)
    diagnosis_tools: Mapped[list[Any]] = mapped_column(default=list)
    diagnosed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Lo marca una persona en el panel: alimenta el conjunto de evaluación.
    feedback: Mapped[Optional[str]] = mapped_column(String(16))  # correcto | incorrecto
    # Gestión por una persona (status: abierto | reconocido | en_curso | resuelto | cerrado).
    assignee: Mapped[Optional[str]] = mapped_column(Unicode(200))
    closed_reason: Mapped[Optional[str]] = mapped_column(String(32))  # solucionado | falso_positivo | ruido | duplicado
    postmortem: Mapped[Optional[str]] = mapped_column(UnicodeText)
    # Tormenta: incidentes casi simultáneos del mismo clúster cuelgan del primero, que se diagnostica por todos.
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), index=True)


class CostEvent(Base):
    """
    Alerta de costo gestionable (fase 4 del plan 10): una anomalía de gasto diario, un presupuesto al 80 %,
    100 % o con pronóstico de superarse, o un export de costos que entrega archivos y ninguna fila. Una por clave.
    """

    __tablename__ = "cost_events"
    __table_args__ = (UniqueConstraint("key", name="uq_cost_events_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32))  # anomalia | presupuesto | export_vacio
    provider: Mapped[str] = mapped_column(String(16))
    account_uid: Mapped[Optional[str]] = mapped_column(String(200))
    day: Mapped[Optional[date]] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    reference: Mapped[Optional[float]] = mapped_column(Float)  # la media de la anomalía o el límite del presupuesto
    title: Mapped[str] = mapped_column(Unicode(300))
    status: Mapped[str] = mapped_column(String(16), default="abierto")  # abierto | reconocido | resuelto | descartado
    assignee: Mapped[Optional[str]] = mapped_column(Unicode(200))
    note: Mapped[Optional[str]] = mapped_column(UnicodeText)
    explanation: Mapped[Optional[str]] = mapped_column(UnicodeText)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[Optional[str]] = mapped_column(Unicode(320))


class SavingAction(Base):
    """
    Oportunidad de ahorro que una persona marcó como aplicada (fase 4 del plan 10). Se verifica sola cuando el
    recurso deja de estar en el inventario: el ahorro realizado es su gasto real de los 30 días previos a la baja.
    """

    __tablename__ = "saving_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource_uid: Mapped[str] = mapped_column(UID, index=True)
    name: Mapped[str] = mapped_column(Unicode(260))
    category: Mapped[str] = mapped_column(Unicode(100))
    expected_monthly: Mapped[float] = mapped_column(Float)
    note: Mapped[Optional[str]] = mapped_column(UnicodeText)
    applied_by: Mapped[str] = mapped_column(Unicode(320))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ControlException(Base):
    """
    Excepción aprobada de un control (CIS o ISO) con su vencimiento: mientras rige, el control se
    muestra como exceptuado en vez de no cumple. Al vencer, vuelve a su estado real.
    """

    __tablename__ = "control_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    framework: Mapped[str] = mapped_column(String(64))
    control: Mapped[str] = mapped_column(String(64))
    justification: Mapped[str] = mapped_column(UnicodeText)
    created_by: Mapped[str] = mapped_column(Unicode(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    until: Mapped[date] = mapped_column(Date)
    revoked_by: Mapped[Optional[str]] = mapped_column(Unicode(320))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IncidentEvent(Base):
    """Línea de tiempo de un incidente: lo que hizo la fuente, el agente y cada persona."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(Unicode(200))  # una persona, "alertmanager" o "agente"
    kind: Mapped[str] = mapped_column(String(32))  # abierto | alerta | diagnostico | estado | asignado | nota | resuelto | tormenta | postmortem
    text: Mapped[str] = mapped_column(UnicodeText)


class IncidentAction(Base):
    """
    Acción de seguimiento de un incidente (fase 7, plan 12): sale de las viñetas de **Acciones** del post-mortem o
    se agrega a mano. Las abiertas aparecen en *Mis pendientes* de su responsable.
    """

    __tablename__ = "incident_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    text: Mapped[str] = mapped_column(Unicode(500))
    owner: Mapped[Optional[str]] = mapped_column(Unicode(200))
    created_by: Mapped[str] = mapped_column(Unicode(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

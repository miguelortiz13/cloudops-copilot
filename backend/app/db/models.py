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

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Numeric, String, Unicode, UnicodeText, UniqueConstraint
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
    # {"CIS Azure 2.1": ["3.7"], "ISO 27001:2022": ["A.8.20"]}
    frameworks: Mapped[dict[str, Any]] = mapped_column(default=dict)
    remediation: Mapped[Optional[str]] = mapped_column(UnicodeText)


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

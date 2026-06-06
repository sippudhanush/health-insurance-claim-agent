import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PolicyCheck(Base):
    __tablename__ = "policy_checks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"PC_{uuid.uuid4().hex[:8].upper()}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )
    check_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FraudCheck(Base):
    __tablename__ = "fraud_checks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"FC_{uuid.uuid4().hex[:8].upper()}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )
    fraud_score: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"DEC_{uuid.uuid4().hex[:8].upper()}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String, nullable=False)
    approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    rejection_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    line_item_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    degradation_notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

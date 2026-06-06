import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Float, Text, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"CLM_{uuid.uuid4().hex[:8].upper()}"
    )
    member_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    claim_category: Mapped[str] = mapped_column(String, nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    hospital_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ytd_claims_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    claims_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    simulate_component_failure: Mapped[bool | None] = mapped_column(
        JSON, nullable=True, name="simulate_component_failure"
    )

    status: Mapped[str] = mapped_column(String, nullable=False, default="RECEIVED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rejection_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"DOC_{uuid.uuid4().hex[:8].upper()}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_type: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_type: Mapped[str | None] = mapped_column(String, nullable=True)
    quality: Mapped[str | None] = mapped_column(String, nullable=True)
    patient_name_on_doc: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class FileStatus(Base):
    __tablename__ = "file_status"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"FS_{uuid.uuid4().hex[:8].upper()}"
    )
    claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("claims.id"), nullable=False, index=True
    )
    file_uuid: Mapped[str] = mapped_column(String, nullable=False)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    actual_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

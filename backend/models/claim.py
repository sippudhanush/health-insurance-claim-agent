import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Float, Text
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
    trace: Mapped[str | None] = mapped_column(Text, nullable=True)

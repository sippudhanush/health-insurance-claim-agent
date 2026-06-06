import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Text, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


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

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.document import Document
from schemas.document import LightExtractionResult
from services.llm_client import groq_client


class ExtractionAgent:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.degraded = False

    async def light_extract(
        self, claim_id: str, documents: list[dict]
    ) -> list[LightExtractionResult]:
        results = []
        for doc in documents:
            try:
                content_for_llm = self._build_light_prompt(doc)
                extracted = await groq_client.light_extract(content_for_llm)
                result = LightExtractionResult(
                    file_id=doc["file_id"],
                    detected_type=extracted.get(
                        "detected_type", doc.get("actual_type")
                    ),
                    quality=extracted.get("quality", doc.get("quality", "GOOD")),
                    patient_name_on_doc=extracted.get(
                        "patient_name", doc.get("patient_name_on_doc")
                    ),
                    confidence=extracted.get("confidence", 0.9),
                )
            except Exception as e:
                self.degraded = True
                result = LightExtractionResult(
                    file_id=doc["file_id"],
                    detected_type=doc.get("actual_type"),
                    quality=doc.get("quality", "GOOD"),
                    patient_name_on_doc=doc.get("patient_name_on_doc"),
                    confidence=0.5,
                    error=str(e),
                )

            db_doc = Document(
                claim_id=claim_id,
                file_id=doc["file_id"],
                file_name=doc.get("file_name"),
                actual_type=doc.get("actual_type"),
                detected_type=result.detected_type,
                quality=result.quality,
                patient_name_on_doc=result.patient_name_on_doc,
                extraction_confidence=result.confidence,
            )
            self.db.add(db_doc)
            results.append(result)

        await self.db.flush()
        return results

    async def deep_extract(
        self, claim_id: str, validated_docs: list[dict]
    ) -> list[dict]:
        result_docs = []
        for doc in validated_docs:
            try:
                content = self._build_deep_prompt(doc)
                extracted = await groq_client.deep_extract(
                    doc.get("detected_type", doc.get("actual_type", "UNKNOWN")),
                    content,
                )
                confidence = (
                    extracted.pop("confidence", 0.9)
                    if isinstance(extracted, dict)
                    else 0.9
                )
            except Exception as e:
                self.degraded = True
                extracted = {"extraction_error": str(e)}
                confidence = 0.4

            query = select(Document).where(
                Document.claim_id == claim_id,
                Document.file_id == doc["file_id"],
            )
            result = await self.db.execute(query)
            db_doc = result.scalar_one_or_none()
            if db_doc:
                db_doc.extracted_content = extracted
                db_doc.extraction_confidence = confidence
                self.db.add(db_doc)

            result_docs.append(
                {
                    "file_id": doc["file_id"],
                    "detected_type": doc.get("detected_type", doc.get("actual_type")),
                    "extracted_content": extracted,
                    "confidence": confidence,
                    "quality": doc.get("quality", "GOOD"),
                }
            )

        await self.db.flush()
        return result_docs

    def _build_light_prompt(self, doc: dict) -> str:
        parts = [f"File: {doc.get('file_name', doc['file_id'])}"]
        if doc.get("actual_type"):
            parts.append(f"Expected type: {doc['actual_type']}")
        if doc.get("content"):
            parts.append(f"Content: {doc['content']}")
        if doc.get("quality") == "UNREADABLE":
            parts.append("NOTE: This document is marked as unreadable / blurry.")
        if doc.get("patient_name_on_doc"):
            parts.append(f"Patient on doc: {doc['patient_name_on_doc']}")
        return "\n".join(parts)

    def _build_deep_prompt(self, doc: dict) -> str:
        content = doc.get("extracted_content") or doc.get("content") or {}
        return f"""Document type: {doc.get("detected_type", doc.get("actual_type", "UNKNOWN"))}
File: {doc.get("file_name", doc["file_id"])}
Content: {content}
Quality: {doc.get("quality", "GOOD")}"""

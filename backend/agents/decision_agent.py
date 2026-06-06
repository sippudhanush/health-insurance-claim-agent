from sqlalchemy.ext.asyncio import AsyncSession
from models import DecisionRecord
from schemas.decision import (
    DecisionOutput,
    PolicyResult,
    FraudResult,
    LineItemBreakdown,
)
from agents.extraction_agent import ExtractionAgent


class DecisionEngineAgent:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def decide(
        self,
        claim_id: str,
        validation_result,
        extracted_docs: list[dict],
        policy_result: PolicyResult,
        fraud_result: FraudResult,
        extraction_agent: ExtractionAgent,
        claimed_amount: float,
    ) -> DecisionOutput:
        trace = {
            "claim_id": claim_id,
            "stages": {
                "extraction": {
                    "status": "DEGRADED" if extraction_agent.degraded else "PASSED",
                    "document_count": len(extracted_docs),
                    "documents": [
                        {
                            "file_id": d["file_id"],
                            "type": d.get("detected_type"),
                            "confidence": d.get("confidence"),
                        }
                        for d in extracted_docs
                    ],
                },
                "validation": {
                    "status": "PASSED" if validation_result.valid else "FAILED",
                    "errors": [e.model_dump() for e in validation_result.errors]
                    if validation_result.errors
                    else [],
                },
                "policy": {
                    "status": "PASSED" if policy_result.eligible else "REJECTED",
                    "checks": [c.model_dump() for c in policy_result.checks],
                    "rejection_reasons": policy_result.rejection_reasons,
                },
                "fraud": {
                    "status": "FLAGGED" if fraud_result.fraud_score >= 0.8 else "CLEAR",
                    "fraud_score": fraud_result.fraud_score,
                    "signals": fraud_result.signals,
                },
            },
        }

        degradation_notes: list[str] = []
        if extraction_agent.degraded:
            degradation_notes.append(
                "Document extraction ran with degraded quality. Some fields may be missing."
            )
            degradation_notes.append(
                "Manual review recommended due to incomplete processing."
            )

        rejection_reasons = list(policy_result.rejection_reasons)

        if not validation_result.valid:
            return DecisionOutput(
                claim_id=claim_id,
                decision="REJECTED",
                approved_amount=0.0,
                confidence_score=0.95,
                rejection_reasons=[e.code for e in validation_result.errors],
                trace=trace,
            )

        if fraud_result.fraud_score >= 0.8:
            trace["stages"]["fraud"]["routed_to"] = "MANUAL_REVIEW"
            return DecisionOutput(
                claim_id=claim_id,
                decision="MANUAL_REVIEW",
                approved_amount=0.0,
                confidence_score=fraud_result.fraud_score,
                rejection_reasons=["FRAUD_FLAG"],
                trace=trace,
            )

        if not policy_result.eligible:
            return DecisionOutput(
                claim_id=claim_id,
                decision="REJECTED",
                approved_amount=0.0,
                confidence_score=0.95,
                rejection_reasons=rejection_reasons,
                trace=trace,
            )

        line_item_breakdown = self._build_line_item_breakdown(
            extracted_docs, policy_result, claimed_amount
        )

        base_confidence = 0.95
        confidence_penalty = 0.0
        if extraction_agent.degraded:
            confidence_penalty += 0.15
        if fraud_result.fraud_score > 0:
            confidence_penalty += 0.05
        if policy_result.copay_percent > 0:
            confidence_penalty += 0.0

        confidence_score = round(max(base_confidence - confidence_penalty, 0.3), 2)

        approved_amount = policy_result.approved_amount_estimate or 0.0

        decision = "APPROVED"
        if approved_amount < claimed_amount:
            decision = "PARTIAL"

        if extraction_agent.degraded:
            decision = "APPROVED"

        dec_record = DecisionRecord(
            claim_id=claim_id,
            decision=decision,
            approved_amount=approved_amount,
            confidence_score=confidence_score,
            rejection_reasons=rejection_reasons,
            line_item_breakdown=[l.model_dump() for l in line_item_breakdown]
            if line_item_breakdown
            else None,
            trace=trace,
            degradation_notes=degradation_notes or None,
        )
        self.db.add(dec_record)
        await self.db.flush()

        return DecisionOutput(
            claim_id=claim_id,
            decision=decision,
            approved_amount=approved_amount,
            confidence_score=confidence_score,
            rejection_reasons=rejection_reasons,
            line_item_breakdown=line_item_breakdown,
            trace=trace,
            degradation_notes=degradation_notes,
        )

    def _build_line_item_breakdown(
        self,
        extracted_docs: list[dict],
        policy_result: PolicyResult,
        claimed_amount: float,
    ) -> list[LineItemBreakdown] | None:
        line_items = []
        for doc in extracted_docs:
            content = doc.get("extracted_content") or doc.get("content") or {}
            if isinstance(content, dict):
                items = content.get("line_items", []) or content.get("medicines", [])
                for item in items:
                    if isinstance(item, dict):
                        desc = item.get("description", item.get("name", str(item)))
                        amt = float(item.get("amount", 0))
                        line_items.append({"description": desc, "amount": amt})

        if not line_items:
            return None

        breakdown = []
        excluded = self._get_excluded_terms(policy_result)
        for li in line_items:
            desc = li["description"]
            amt = li["amount"]
            is_excluded = any(e.lower() in desc.lower() for e in excluded)
            reason = None
            if is_excluded:
                reason = "Excluded under policy"
            breakdown.append(
                LineItemBreakdown(
                    description=desc,
                    amount=amt,
                    approved=not is_excluded,
                    reason=reason,
                )
            )
        return breakdown

    def _get_excluded_terms(self, policy_result: PolicyResult) -> list[str]:
        return [
            "teeth whitening",
            "veneers",
            "orthodontic",
            "braces",
            "implants",
            "bleaching",
            "lasik",
            "refractive surgery",
            "cosmetic",
            "bariatric",
            "obesity",
            "weight loss",
        ]

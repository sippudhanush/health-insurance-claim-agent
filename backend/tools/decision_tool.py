from sqlalchemy.ext.asyncio import AsyncSession
from core.tool import Tool
from models import DecisionRecord


EXCLUDED_TERMS = [
    "teeth whitening", "veneers", "orthodontic", "braces", "implants",
    "bleaching", "lasik", "refractive surgery", "cosmetic", "bariatric",
    "obesity", "weight loss",
]


class DecideClaimTool(Tool):
    def __init__(self, db: AsyncSession):
        self.db = db

    @property
    def name(self) -> str:
        return "decide_claim"

    @property
    def description(self) -> str:
        return "Make a final claim decision (APPROVED/PARTIAL/REJECTED/MANUAL_REVIEW) based on all previous stage results. Must be called last."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "claimed_amount": {"type": "number"},
                "validation": {
                    "type": "object",
                    "properties": {
                        "valid": {"type": "boolean"},
                        "errors": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "extraction": {
                    "type": "object",
                    "properties": {
                        "documents": {"type": "array", "items": {"type": "object"}},
                        "degraded": {"type": "boolean"},
                        "count": {"type": "integer"},
                    },
                },
                "deep_extraction": {
                    "type": "object",
                    "properties": {
                        "documents": {"type": "array", "items": {"type": "object"}},
                        "degraded": {"type": "boolean"},
                    },
                },
                "policy": {
                    "type": "object",
                    "properties": {
                        "eligible": {"type": "boolean"},
                        "approved_amount_estimate": {"type": "number"},
                        "checks": {"type": "array", "items": {"type": "object"}},
                        "rejection_reasons": {"type": "array", "items": {"type": "string"}},
                        "copay_percent": {"type": "number"},
                    },
                },
                "fraud": {
                    "type": "object",
                    "properties": {
                        "fraud_score": {"type": "number"},
                        "signals": {"type": "array", "items": {"type": "string"}},
                        "flagged": {"type": "boolean"},
                    },
                },
            },
            "required": ["claim_id", "claimed_amount", "validation", "extraction", "policy", "fraud"],
        }

    async def run(
        self,
        claim_id: str,
        claimed_amount: float,
        validation: dict,
        extraction: dict,
        deep_extraction: dict | None = None,
        policy: dict | None = None,
        fraud: dict | None = None,
    ) -> dict:
        deep_docs = (deep_extraction or extraction).get("documents", [])
        is_degraded = extraction.get("degraded", False) or (deep_extraction or {}).get("degraded", False)
        valid = validation.get("valid", False)
        fraud_score = (fraud or {}).get("fraud_score", 0.0)
        policy_eligible = (policy or {}).get("eligible", True)
        approved_amt = (policy or {}).get("approved_amount_estimate", 0.0) or 0.0
        rejection_reasons = list((policy or {}).get("rejection_reasons", []))
        checks = (policy or {}).get("checks", [])
        signals = (fraud or {}).get("signals", [])

        trace = {
            "claim_id": claim_id,
            "stages": {
                "extraction": {
                    "status": "DEGRADED" if is_degraded else "PASSED",
                    "document_count": extraction.get("count", len(deep_docs)),
                    "documents": [
                        {"file_id": d["file_id"], "type": d.get("detected_type"), "confidence": d.get("confidence")}
                        for d in deep_docs
                    ],
                },
                "validation": {
                    "status": "PASSED" if valid else "FAILED",
                    "errors": validation.get("errors", []),
                },
                "policy": {
                    "status": "PASSED" if policy_eligible else "REJECTED",
                    "checks": checks,
                    "rejection_reasons": rejection_reasons,
                },
                "fraud": {
                    "status": "FLAGGED" if fraud_score >= 0.8 else "CLEAR",
                    "fraud_score": fraud_score,
                    "signals": signals,
                },
            },
        }

        degradation_notes = []
        if is_degraded:
            degradation_notes.append("Document extraction ran with degraded quality. Some fields may be missing.")
            degradation_notes.append("Manual review recommended due to incomplete processing.")

        if not valid:
            decision = "REJECTED"
            approved_amount = 0.0
            confidence = 0.95
            rejection_reasons = [e.get("code", "DOCUMENT_ERROR") for e in validation.get("errors", [])]
        elif fraud_score >= 0.8:
            decision = "MANUAL_REVIEW"
            approved_amount = 0.0
            confidence = fraud_score
            trace["stages"]["fraud"]["routed_to"] = "MANUAL_REVIEW"
            rejection_reasons = ["FRAUD_FLAG"]
        elif not policy_eligible:
            decision = "REJECTED"
            approved_amount = 0.0
            confidence = 0.95
        else:
            line_item_breakdown = self._build_line_item_breakdown(deep_docs, approved_amt, claimed_amount)

            base_confidence = 0.95
            penalty = 0.0
            if is_degraded:
                penalty += 0.15
            if fraud_score > 0:
                penalty += 0.05
            confidence = round(max(base_confidence - penalty, 0.3), 2)

            approved_amount = approved_amt
            decision = "APPROVED"
            if approved_amount < claimed_amount:
                decision = "PARTIAL"
            if is_degraded:
                decision = "APPROVED"

        dec_record = DecisionRecord(
            claim_id=claim_id,
            decision=decision,
            approved_amount=approved_amount,
            confidence_score=confidence,
            rejection_reasons=rejection_reasons,
            line_item_breakdown=line_item_breakdown if decision in ("APPROVED", "PARTIAL") else None,
            trace=trace,
            degradation_notes=degradation_notes or None,
        )
        self.db.add(dec_record)
        await self.db.flush()

        return {
            "claim_id": claim_id,
            "decision": decision,
            "approved_amount": approved_amount,
            "confidence_score": confidence,
            "rejection_reasons": rejection_reasons,
            "line_item_breakdown": line_item_breakdown if decision in ("APPROVED", "PARTIAL") else None,
            "trace": trace,
            "degradation_notes": degradation_notes,
        }

    def _build_line_item_breakdown(self, docs: list[dict], approved_amt: float, claimed_amount: float) -> list[dict] | None:
        line_items = []
        for doc in docs:
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
        for li in line_items:
            desc = li["description"]
            amt = li["amount"]
            is_excluded = any(e.lower() in desc.lower() for e in EXCLUDED_TERMS)
            breakdown.append({
                "description": desc,
                "amount": amt,
                "approved": not is_excluded,
                "reason": "Excluded under policy" if is_excluded else None,
            })
        return breakdown

from sqlalchemy.ext.asyncio import AsyncSession
from core.tool import Tool
from services.llm_client import groq_client
from models import DecisionRecord
import json


DECISION_SYSTEM_PROMPT = """You are a claim decision agent for health insurance. Your job is to produce the final decision for a claim based on all previous stage results.

You will receive:
1. Claim details (claim_id, claimed_amount)
2. Validation results (valid flag, errors if any)
3. Extraction results (documents, degraded flag)
4. Policy evaluation results (eligible, approved_amount_estimate, checks, rejection_reasons)
5. Fraud detection results (fraud_score, signals, flagged)

Make a decision using these rules in priority order:

1. If validation failed (errors exist): decision = REJECTED, approved_amount = 0
2. If fraud_score >= 0.8: decision = MANUAL_REVIEW, approved_amount = 0
3. If policy ineligible: decision = REJECTED, approved_amount = 0
4. If eligible:
   - If extraction was degraded: decision = APPROVED (overrides partial), approved_amount = approved_amount_estimate
   - Else if approved_amount_estimate < claimed_amount: decision = PARTIAL
   - Else: decision = APPROVED

Confidence score:
- Start at 0.95
- Subtract 0.15 if extraction was degraded
- Subtract 0.05 if fraud_score > 0
- Minimum 0.30

Line item breakdown (if available):
- Go through extracted documents' line_items or medicines
- Check if any item description matches excluded terms (teeth whitening, veneers, orthodontic, braces, implants, bleaching, lasik, refractive surgery, cosmetic, bariatric, obesity, weight loss)
- Mark excluded items as approved=false with reason "Excluded under policy"

Return a JSON object with:
{
  "claim_id": "<id>",
  "decision": "APPROVED" or "PARTIAL" or "REJECTED" or "MANUAL_REVIEW",
  "approved_amount": <number>,
  "confidence_score": <number>,
  "rejection_reasons": ["REASON1", ...],
  "line_item_breakdown": [{"description": "...", "amount": <number>, "approved": true/false, "reason": "..."}],
  "trace": {
    "claim_id": "<id>",
    "stages": {
      "extraction": {"status": "PASSED" or "DEGRADED", "document_count": <number>, "documents": [...]},
      "validation": {"status": "PASSED" or "FAILED", "errors": [...]},
      "policy": {"status": "PASSED" or "REJECTED", "checks": [...], "rejection_reasons": [...]},
      "fraud": {"status": "CLEAR" or "FLAGGED", "fraud_score": <number>, "signals": [...]}
    }
  },
  "degradation_notes": ["Note 1", ...]
}"""


class DecideClaimTool(Tool):
    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    @property
    def name(self) -> str:
        return "decide_claim"

    @property
    def description(self) -> str:
        return "Make a final claim decision based on all previous stage results using an LLM."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "claimed_amount": {"type": "number"},
                "validation": {"type": "object"},
                "extraction": {"type": "object"},
                "deep_extraction": {"type": "object"},
                "policy": {"type": "object"},
                "fraud": {"type": "object"},
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
        user_content = json.dumps({
            "claim_id": claim_id,
            "claimed_amount": claimed_amount,
            "validation": validation,
            "extraction": extraction,
            "deep_extraction": deep_extraction or extraction,
            "policy": policy or {},
            "fraud": fraud or {},
        }, indent=2, default=str)

        result = await groq_client.structured_extract(DECISION_SYSTEM_PROMPT, user_content, max_tokens=4000)

        if self.db:
            dec_record = DecisionRecord(
                claim_id=claim_id,
                decision=result.get("decision"),
                approved_amount=result.get("approved_amount"),
                confidence_score=result.get("confidence_score"),
                rejection_reasons=result.get("rejection_reasons", []),
                line_item_breakdown=result.get("line_item_breakdown"),
                trace=result.get("trace", {}),
                degradation_notes=result.get("degradation_notes"),
            )
            self.db.add(dec_record)
            await self.db.flush()

        return result

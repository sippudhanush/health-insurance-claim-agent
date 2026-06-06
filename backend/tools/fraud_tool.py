from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from core.tool import Tool
from services.llm_client import groq_client
from models import Claim, FraudCheck
import json


FRAUD_SYSTEM_PROMPT = """You are a fraud detection agent for health insurance claims. Your job is to assess the fraud risk of a claim.

You will receive:
1. Claim details (member_id, claimed_amount, treatment_date)
2. Claims history for this member (dates and amounts of previous claims)
3. Fraud thresholds from policy (same_day_claims_limit, monthly_claims_limit, high_value_claim_threshold, etc.)

Analyze for these fraud signals:

1. **SAME_DAY_CLAIMS**: Are there multiple claims on the same treatment date? If count exceeds same_day_claims_limit, flag it.
2. **HIGH_MONTHLY_VOLUME**: Are there many claims in the same month? If count exceeds monthly_claims_limit, flag it.
3. **HIGH_VALUE_CLAIM**: Is the claimed amount above high_value_claim_threshold? Flag it.
4. **Any other suspicious patterns** you notice in the data.

Return a JSON object with:
{
  "fraud_score": <number 0.0 to 1.0>,
  "flagged": <true if fraud_score >= fraud_score_manual_review_threshold>,
  "signals": ["SIGNAL_DESCRIPTION_1", "SIGNAL_DESCRIPTION_2"]
}

fraud_score should be:
- 0.0 if no signals
- 0.5 for same_day_claims exceeded
- 0.3 for high monthly volume
- 0.2 for high value claim
- Cumulative, capped at 1.0

Be fair and evidence-based. Only flag what the data supports."""


class DetectFraudTool(Tool):
    def __init__(self, db: AsyncSession | None = None, policy_terms: dict | None = None):
        self.db = db
        self.policy_terms = policy_terms

    @property
    def name(self) -> str:
        return "detect_fraud"

    @property
    def description(self) -> str:
        return "Detect potential fraud signals for a claim using LLM analysis of claims history and policy thresholds."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "member_id": {"type": "string"},
                "claimed_amount": {"type": "number"},
                "treatment_date": {"type": "string", "format": "date"},
                "claims_history": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional previous claims history",
                },
            },
            "required": ["claim_id", "member_id", "claimed_amount", "treatment_date"],
        }

    async def run(
        self,
        claim_id: str,
        member_id: str,
        claimed_amount: float,
        treatment_date: str,
        claims_history: list[dict] | None = None,
    ) -> dict:
        if isinstance(treatment_date, str):
            treatment_date = date.fromisoformat(treatment_date)

        claims_data = claims_history or []
        if not claims_data and self.db:
            result = await self.db.execute(
                select(Claim.id, Claim.claimed_amount, Claim.created_at)
                .where(Claim.member_id == member_id, Claim.id != claim_id)
            )
            claims_data = [
                {"date": str(row.created_at.date()) if hasattr(row, 'created_at') else str(treatment_date),
                 "amount": float(row.claimed_amount)}
                for row in result.all()
            ]

        fraud_thresholds = {}
        if self.policy_terms:
            fraud_thresholds = self.policy_terms.get("fraud_thresholds", {})

        user_content = json.dumps({
            "claim": {
                "member_id": member_id,
                "claimed_amount": claimed_amount,
                "treatment_date": str(treatment_date),
            },
            "claims_history": claims_data,
            "fraud_thresholds": fraud_thresholds,
        }, indent=2, default=str)

        result = await groq_client.structured_extract(FRAUD_SYSTEM_PROMPT, user_content)

        if self.db:
            self.db.add(FraudCheck(
                claim_id=claim_id,
                fraud_score=result.get("fraud_score", 0.0),
                signals=result.get("signals", []),
            ))
            await self.db.flush()

        return result

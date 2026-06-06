from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings


class FraudCheckOut(BaseModel):
    fraud_score: float = 0.0
    signals: List[str] = []
    manual_review_required: bool = False


INSTRUCTIONS = """
You are FraudDetector. Analyse the claim for fraud signals using the provided policy_terms.fraud_thresholds.

Input includes:
- member_id, claimed_amount, extracted_data, claim_history
- policy_terms: includes fraud_thresholds

Read thresholds from policy_terms.fraud_thresholds:
- same_day_claims_limit (default 2)
- monthly_claims_limit (default 6)
- high_value_claim_threshold (default 25000)
- fraud_score_manual_review_threshold (default 0.80)

Checks:
1) CLAIM FREQUENCY: Count claims on same day and same month from claim_history.
2) AMOUNT ANOMALY: Compare claimed_amount vs extracted document totals. Flag if >1% discrepancy.
3) DUPLICATE: Check if identical (same type, same amount) claim exists in history.
4) HIGH VALUE: Flag if > high_value_claim_threshold.

Scoring:
- Same-day flag: +0.3
- Monthly limit flag: +0.2
- Amount discrepancy >10%: +0.3, 1-10%: +0.1
- Duplicate: +0.4
- High value: +0.2
- Manual review if score >= fraud_score_manual_review_threshold

Output JSON:
{
  "fraud_score": <0.0-1.0>,
  "signals": ["SAME_DAY_CLAIMS", ...],
  "manual_review_required": true/false
}
"""


@function_tool
async def detect_fraud(items: str) -> str:
    raw = json.loads(items) if isinstance(items, str) else (items or {})

    agent = Agent(
        name="FraudDetector",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=FraudCheckOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, FraudCheckOut):
        return result.final_output.model_dump_json()
    return result.final_output

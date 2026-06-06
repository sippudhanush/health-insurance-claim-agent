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
You are FraudDetector. Analyse the claim for fraud signals.

Input includes:
- member_id (string)
- claimed_amount (float)
- extracted_data (object) - extracted document data with totals
- claim_history (list) - previous claims with dates and amounts
- fraud_thresholds (object) - configuration thresholds

Checks to perform:
1) CLAIM FREQUENCY - Check if member has more than 2 claims on the same day or more than 6 in a month.
2) AMOUNT ANOMALY - Compare claimed amount against extracted totals from documents. Flag if discrepancy > 1%.
3) DUPLICATE CHECK - Check if an identical claim (same type, same amount) exists in history.
4) HIGH VALUE - Flag claims above 25000 for manual review.

Scoring:
- Start at 0.0
- Same-day flag: +0.3
- Monthly limit flag: +0.2
- Amount discrepancy > 10%: +0.3
- Amount discrepancy 1-10%: +0.1
- Duplicate claim: +0.4
- High value (>25000): +0.2
- Manual review if fraud_score >= 0.80 OR claimed_amount > 25000

Return ONLY the final JSON with no extra text.

Final output JSON:
{
  "fraud_score": <0.0-1.0>,
  "signals": ["SAME_DAY_CLAIMS", "AMOUNT_MISMATCH", ...],
  "manual_review_required": true/false
}
"""


@function_tool
async def detect_fraud(items: str) -> str:
    items_list = json.loads(items) if isinstance(items, str) else (items or [])

    agent = Agent(
        name="FraudDetector",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=FraudCheckOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(items_list, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, FraudCheckOut):
        return result.final_output.model_dump_json()
    return result.final_output

from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings, AgentOutputSchema
from pydantic import ConfigDict

from health_insurance_agent.config import CLAIM_AGENT_MODEL


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class FraudCheckOut(BaseModel):
    fraud_score: float = 0.0
    signals: List[str] = []
    manual_review_required: bool = False


INSTRUCTIONS = """
You are FraudDetector. Analyse the claim for fraud signals.

Input includes:
- member_id, claimed_amount, extracted_data, claim_history, treatment_date
- policy_terms: includes fraud_thresholds

Thresholds (from policy_terms.fraud_thresholds):
- same_day_claims_limit = value or 2
- monthly_claims_limit = value or 6
- high_value_claim_threshold = value or 25000
- fraud_score_manual_review_threshold = value or 0.80

Steps:
1. Count same-day claims: claim_history entries matching the current claim's date, PLUS the current claim itself.
2. Count same-month claims: claim_history entries in same month as current claim, PLUS the current claim.
3. Compute fraud_score (0.0 to 1.0, cumulative):
   - For each same-day claim beyond same_day_claims_limit: add 0.2
   - If same-month total > monthly_claims_limit: add 0.2
   - If amount discrepancy >10%: add 0.3; if 1-10%: add 0.1
   - If duplicate claim in history: add 0.4
   - If claimed_amount > high_value_claim_threshold: add 0.2
   Cap at 1.0.

4. Determine manual_review_required:
   Set to true if ANY condition below is met:
   (a) fraud_score >= fraud_score_manual_review_threshold
   (b) (same-day total) - same_day_claims_limit >= 2
   (c) duplicate claim found
   Otherwise set to false.

IMPORTANT: Condition (b) is NOT about the score. It is a separate rule.
Example: 4 total same-day claims, limit 2 → 4-2=2 → manual_review_required=true.

Output JSON exactly:
{
  "fraud_score": <number>,
  "signals": [<string>, ...],
  "manual_review_required": <bool>
}
"""


@function_tool(strict_mode=False)
async def detect_fraud(items: ToolInput) -> str:
    raw = items.model_dump() if not isinstance(items, dict) else items

    agent = Agent(
        name="FraudDetector",
        instructions=INSTRUCTIONS,
        model=CLAIM_AGENT_MODEL,
        output_type=AgentOutputSchema(FraudCheckOut, strict_json_schema=False),
        model_settings=ModelSettings(),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=5,
    )

    if isinstance(result.final_output, FraudCheckOut):
        return result.final_output.model_dump_json()
    return result.final_output

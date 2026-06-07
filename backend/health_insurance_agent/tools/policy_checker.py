from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings, AgentOutputSchema
from pydantic import ConfigDict

from health_insurance_agent.config import CLAIM_AGENT_MODEL


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class PolicyCheckItem(BaseModel):
    check_name: str
    status: str
    detail: Optional[str] = None


class PolicyCheckOut(BaseModel):
    eligible: bool
    approved_amount_estimate: Optional[float] = None
    checks: List[PolicyCheckItem] = []
    network_discount_percent: float = 0.0
    copay_percent: float = 0.0
    rejection_reasons: List[str] = []
    line_item_breakdown: Optional[List[dict]] = None


INSTRUCTIONS = """
You are PolicyChecker. Evaluate a claim against the provided policy_terms.

Input includes:
- claim: {member_id, claim_category, claimed_amount, treatment_date, hospital_name}
- extracted_data: extracted document info (diagnosis, line_items[], total_amount, medicines[], ...)
- member: {member_id, name, join_date, relationship, ...}
- policy_terms: full policy configuration

Run these checks using values from policy_terms — do NOT hardcode:

1) WAITING PERIOD: Compare join_date + treatment_date. Check initial_waiting_period_days. Check specific_conditions (diabetes=90d, etc.) if diagnosis matches. On failure, state eligibility date.

2) PER-CLAIM LIMIT: Read per_claim_limit from policy_terms.coverage. If claimed_amount > per_claim_limit, reject with PER_CLAIM_EXCEEDED.

3) SUB-LIMIT: Read category sub_limit from policy_terms.opd_categories[claim_category]. If claimed_amount > sub_limit, cap at sub_limit.

4) EXCLUSIONS — LINE-ITEM LEVEL:
   - Check EACH line item's description against exclusions:
     - For DENTAL claims: check dental_exclusions list
     - For VISION claims: check vision_exclusions list
     - For all claims: check conditions list
   - Build a line_item_breakdown: mark each item as approved:true or approved:false with reason
   - Sum approved items' amounts for the approved_amount_estimate
   - If some items excluded and some not, this is a PARTIAL approval — keep eligible=true but list rejection_reasons for excluded items

5) PRE-AUTHORIZATION: If tests_ordered include MRI/CT/PET and amount > pre_auth_threshold from category config, require pre-auth. Reject with PRE_AUTH_MISSING.

6) NETWORK HOSPITAL: Compare hospital_name EXACTLY against the policy_terms.network_hospitals list. Do NOT infer or assume a hospital is in-network. If the name does not appear verbatim in the list, set network_discount_percent = 0.

7) CO-PAY: Read copay_percent from category config. Apply network discount BEFORE co-pay.

8) APPROVED AMOUNT: Start from sum of approved line items. Apply network discount, then co-pay. Cap at sub_limit if needed.

Return "PASSED", "FAILED", or "WAIVED" per check.

Output JSON:
{
  "eligible": true/false,
  "approved_amount_estimate": <number|null>,
  "checks": [{"check_name": "...", "status": "PASSED|FAILED|WAIVED", "detail": "..."}],
  "network_discount_percent": <float>,
  "copay_percent": <float>,
  "rejection_reasons": ["<reason>", ...],
  "line_item_breakdown": [{"description": "...", "amount": <float>, "approved": true/false, "reason": "..."}]
}
"""


@function_tool(strict_mode=False)
async def check_policy(items: ToolInput) -> str:
    raw = items.model_dump() if not isinstance(items, dict) else items

    agent = Agent(
        name="PolicyChecker",
        instructions=INSTRUCTIONS,
        model=CLAIM_AGENT_MODEL,
        output_type=AgentOutputSchema(PolicyCheckOut, strict_json_schema=False),
        model_settings=ModelSettings(),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=5,
    )

    if isinstance(result.final_output, PolicyCheckOut):
        return result.final_output.model_dump_json()
    return result.final_output

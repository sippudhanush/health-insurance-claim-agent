from __future__ import annotations

import json
from typing import List, Optional, Set
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings

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


INSTRUCTIONS = """
You are PolicyChecker. Evaluate a health insurance claim against policy terms using the provided tools.

Policy rules:
1) WAITING PERIOD - Initial waiting period is 30 days from join_date. Specific conditions have longer waiting periods (diabetes: 90d, hypertension: 90d, etc.)
2) SUB-LIMIT - Each category has a sub-limit: consultation=2000, diagnostic=10000, pharmacy=15000, dental=10000, vision=5000, alternative_medicine=8000
3) PER-CLAIM LIMIT - Maximum 5000 per claim
4) EXCLUSIONS - Self-inflicted injuries, war, substance abuse, experimental treatments, infertility, obesity/weight loss, bariatric surgery, cosmetic procedures, vaccination, health supplements
5) PRE-AUTHORIZATION - Required for MRI (above 10000), CT scan (above 10000), PET scan, major surgical procedures
6) CO-PAY - Consultation has 10% co-pay. Network hospitals give discount before co-pay.
7) NETWORK HOSPITALS - Apollo, Fortis, Max, Manipal, Narayana, Medanta, Kokilaben, Aster, Columbia Asia, Sakra World

Selection rules:
1) First check waiting period using join_date and treatment_date.
2) Check exclusions against diagnosis and procedures.
3) Check sub-limit against claimed amount for the category.
4) Check per-claim-limit (5000 max).
5) Check if pre-authorization is needed for high-value or specified procedures.
6) Check if hospital is in-network for discount.
7) Apply co-pay and network discount to compute final approved amount.

For each check, return status: "PASSED", "FAILED", or "WAIVED".

Final output JSON:
{
  "eligible": true/false,
  "approved_amount_estimate": <number|null>,
  "checks": [{"check_name": "...", "status": "PASSED|FAILED|WAIVED", "detail": "..."}],
  "network_discount_percent": <float>,
  "copay_percent": <float>,
  "rejection_reasons": ["<reason>", ...]
}
"""


@function_tool
async def check_policy(items: str) -> str:
    items_list = json.loads(items) if isinstance(items, str) else (items or [])

    agent = Agent(
        name="PolicyChecker",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=PolicyCheckOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(items_list, ensure_ascii=False),
        max_turns=20,
    )

    if isinstance(result.final_output, PolicyCheckOut):
        return result.final_output.model_dump_json()
    return result.final_output

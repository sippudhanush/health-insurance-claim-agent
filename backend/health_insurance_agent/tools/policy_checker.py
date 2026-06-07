from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings, AgentOutputSchema
from pydantic import ConfigDict

from health_insurance_agent.config import CLAIM_AGENT_MODEL

POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "policy_terms.json"


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

Input includes policy_terms, claim, extracted_data (contains line_items with description and amount), and member.

Do NOT compute the approved_amount_estimate yourself — leave it as null. The system will calculate it from your line_item_breakdown, network_discount_percent, and copay_percent.

Run these checks using the data in policy_terms:

1) EXCLUSIONS: Check each line item against exclusions lists. Build line_item_breakdown with approved:true/false.

2) WAITING PERIOD: Compare member.join_date vs claim.treatment_date.

3) PER-CLAIM LIMIT: Compare claim.claimed_amount vs policy_terms.coverage.per_claim_limit.

4) PRE-AUTHORIZATION: Check if category requires pre-auth.

5) NETWORK HOSPITAL: Compare claim.hospital_name against policy_terms.network_hospitals list exactly. Set network_discount_percent from opd_categories if matched.

6) CO-PAY: Read copay_percent from opd_categories[claim.claim_category].copay_percent.

7) SUB-LIMIT: Compare against sub_limit from opd_categories. Informational only — do NOT cap.

Set eligible=true if at least one line item is approved.

Output JSON:
{"eligible": true/false, "approved_amount_estimate": null, "checks": [{"check_name": "...", "status": "PASSED|FAILED|WAIVED", "detail": "..."}], "network_discount_percent": <float>, "copay_percent": <float>, "rejection_reasons": ["..."], "line_item_breakdown": [{"description": "...", "amount": <float>, "approved": true/false, "reason": "..."}]}
"""


@function_tool(strict_mode=False)
async def check_policy(
    claim: dict,
    member: dict,
    extracted_data: dict,
    policy_terms: dict,
) -> str:
    raw = {
        "claim": claim,
        "member": member,
        "extracted_data": extracted_data,
        "policy_terms": policy_terms,
    }

    pt = raw.get("policy_terms", {})
    if not pt or "opd_categories" not in pt:
        with open(POLICY_PATH) as f:
            full_pt = json.load(f)
        raw["policy_terms"] = full_pt
        if "member" in raw and raw["member"] and "member_id" in raw["member"]:
            for m in full_pt.get("members", []):
                if m.get("member_id") == raw["member"]["member_id"]:
                    raw["member"] = m
                    break

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
        out = result.final_output

        approved_sum = 0.0
        if out.line_item_breakdown:
            for item in out.line_item_breakdown:
                if item.get("approved"):
                    approved_sum += float(item.get("amount", 0))
        discount = float(out.network_discount_percent or 0)
        copay = float(out.copay_percent or 0)
        out.approved_amount_estimate = round(
            approved_sum * (1 - discount / 100) * (1 - copay / 100), 2
        )

        claimed = float(raw.get("claim", {}).get("claimed_amount", 0))
        per_claim_limit = float(
            raw.get("policy_terms", {})
            .get("coverage", {})
            .get("per_claim_limit", 0)
        )
        sub_limit = float(
            raw.get("policy_terms", {})
            .get("opd_categories", {})
            .get(raw.get("claim", {}).get("claim_category", ""), {})
            .get("sub_limit", 0)
        )
        for c in out.checks:
            cn = c.check_name.upper() if c.check_name else ""
            if "PER-CLAIM" in cn:
                c.status = "PASSED" if claimed <= per_claim_limit else "FAILED"
                c.detail = f"Claimed {claimed} vs limit {per_claim_limit}"
            if "SUB-LIMIT" in cn:
                c.status = "PASSED"
                c.detail = f"Amount {out.approved_amount_estimate} vs sub-limit {sub_limit} (informational)"

        return out.model_dump_json()
    return result.final_output

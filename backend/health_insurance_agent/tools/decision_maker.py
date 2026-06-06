from __future__ import annotations

import json
import os
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings, AgentOutputSchema


class DecisionOut(BaseModel):
    decision: str
    approved_amount: Optional[float] = None
    confidence_score: float
    rejection_reasons: List[str] = []
    reasoning: str = ""
    line_item_breakdown: Optional[List[dict]] = None
    degradation_notes: List[str] = []


INSTRUCTIONS = """
You are DecisionMaker. Synthesise all upstream outputs into a final claim decision.

Input includes:
- claim: original claim details {claim_id, member_id, claim_category, claimed_amount, ...}
- verification_result: output from document verifier
- extraction_result: output from document extractor
- policy_result: output from policy checker (includes line_item_breakdown, checks[])
- fraud_result: output from fraud detector
- policy_terms: full policy configuration
- simulate_component_failure (optional): if true, one component may have degraded

Decision rules:
- REJECTED if: verification.overall_valid == false, OR policy.eligible == false (and no line items were approved)
- PARTIAL if: policy_result has line_item_breakdown where some items approved and some rejected (e.g. cosmetic exclusion)
- APPROVED if: all checks pass, fraud score < threshold, amount within limits
- MANUAL_REVIEW if: fraud.manual_review_required == true, OR fraud.fraud_score >= threshold, OR claimed_amount > auto_manual_review_above

Confidence scoring:
- Start at 1.0
- Deduct 0.1 for each FAILED policy check (unless it's an exclusion that only applies to specific line items)
- Deduct 0.2 if extraction has any document with confidence < 0.7
- Deduct 0.1 if fraud_score > 0.5
- Deduct 0.15 if degradation_notes is non-empty

Output JSON:
{
  "decision": "APPROVED|PARTIAL|REJECTED|MANUAL_REVIEW",
  "approved_amount": <number|null>,
  "confidence_score": <0.0-1.0>,
  "rejection_reasons": ["<reason>", ...],
  "reasoning": "<step-by-step reasoning explaining exactly why this decision was made>",
  "line_item_breakdown": [{"description": "...", "amount": <float>, "approved": true/false, "reason": "..."}],
  "degradation_notes": ["<note>", ...]
}
"""


@function_tool
async def decide_claim(items: str) -> str:
    raw = json.loads(items) if isinstance(items, str) else (items or {})

    agent = Agent(
        name="DecisionMaker",
        instructions=INSTRUCTIONS,
        model=os.getenv("CLAIM_AGENT_MODEL", "gpt-4o-mini"),
        output_type=AgentOutputSchema(DecisionOut, strict_json_schema=False),
        model_settings=ModelSettings(),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, DecisionOut):
        return result.final_output.model_dump_json()
    return result.final_output

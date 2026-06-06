from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings


class DecisionOut(BaseModel):
    decision: str
    approved_amount: Optional[float] = None
    confidence_score: float
    rejection_reasons: List[str] = []
    reasoning: str = ""


INSTRUCTIONS = """
You are DecisionMaker. Synthesise all upstream agent outputs into a final claim decision.

Input includes:
- claim (object) - original claim details
- verification_result (object) - output from document verifier
- extraction_result (object) - output from document extractor
- policy_result (object) - output from policy checker
- fraud_result (object) - output from fraud detector

Decision rules:
- REJECTED if: verification is not overall_valid, OR policy eligibility is false, OR exclusion matched, OR waiting period not served
- MANUAL_REVIEW if: fraud_score >= 0.80 OR claimed_amount > 25000 OR verification/extraction/policy had DEGRADED status
- APPROVED if: all checks pass, fraud score < 0.80, amount within limits
- PARTIAL if: some policy checks pass but sub-limit or co-pay reduces the amount

Confidence scoring:
- Start at 1.0
- Deduct 0.1 for each DEGRADED agent
- Deduct 0.2 if extraction confidence < 0.7
- Deduct 0.1 if fraud_score > 0.5

Return ONLY the final JSON.

Final output JSON:
{
  "decision": "APPROVED|PARTIAL|REJECTED|MANUAL_REVIEW",
  "approved_amount": <number|null>,
  "confidence_score": <0.0-1.0>,
  "rejection_reasons": ["<reason>", ...],
  "reasoning": "<step-by-step reasoning>"
}
"""


@function_tool
async def decide_claim(items: str) -> str:
    items_list = json.loads(items) if isinstance(items, str) else (items or [])

    agent = Agent(
        name="DecisionMaker",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=DecisionOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(items_list, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, DecisionOut):
        return result.final_output.model_dump_json()
    return result.final_output

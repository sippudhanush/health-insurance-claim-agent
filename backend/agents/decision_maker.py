from openai import AsyncOpenAI
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the final decision agent for health insurance claims.
You receive outputs from all previous agents. Synthesise everything.
Your reason must be specific enough that an ops team member understands
exactly why this decision was made without reading anything else.
Lower confidence if any upstream agent was DEGRADED or had low confidence.

Decision rules:
- APPROVED: all policy checks pass, fraud score < 0.80, amount within limits
- PARTIAL: some checks pass but sub-limit or co-pay reduces amount
- REJECTED: exclusion matched OR waiting period not served OR required docs missing
- MANUAL_REVIEW: fraud score >= 0.80 OR claimed amount > 25000 OR any agent DEGRADED

Return JSON with:
{
  "decision": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
  "approved_amount": <number>,
  "reason": "<specific reason>",
  "confidence": <0.0-1.0>,
  "trace": {
    "document_verification": <agent1 output>,
    "extraction": <agent2 output>,
    "policy_checks": <agent3 output>,
    "fraud_check": <agent4 output>,
    "decision_reasoning": "<your step-by-step reasoning>"
  }
}"""


class DecisionMakerAgent(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str):
        super().__init__(client, model, SYSTEM_PROMPT, tools=None)

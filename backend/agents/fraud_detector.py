import json
from datetime import date, datetime
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from services.llm_client import extract_json

SYSTEM_PROMPT = """You are a fraud detection agent for insurance claims.
Analyse the claim for anomalies. Be analytical, not accusatory.
Score between 0.0 (clean) and 1.0 (high risk). Above 0.80 forces manual review."""


class FraudDetectorAgent(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str, policy_terms: dict):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_claim_frequency",
                    "description": "Check how many claims the member has filed recently",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "member_id": {"type": "string"},
                            "claim_history": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["member_id", "claim_history"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_amount_anomaly",
                    "description": "Compare claimed amount against extracted totals from documents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claimed_amount": {"type": "number"},
                            "extracted_data": {"type": "object"},
                        },
                        "required": ["claimed_amount", "extracted_data"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_duplicate",
                    "description": "Check if this claim is a duplicate of a previous one",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_type": {"type": "string"},
                            "claimed_amount": {"type": "number"},
                            "claim_history": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["claim_type", "claimed_amount", "claim_history"],
                    },
                },
            },
        ]
        super().__init__(client, model, SYSTEM_PROMPT, tools)
        self.policy_terms = policy_terms
        self.register_tool("check_claim_frequency", self._check_claim_frequency)
        self.register_tool("check_amount_anomaly", self._check_amount_anomaly)
        self.register_tool("check_duplicate", self._check_duplicate)

    async def _check_claim_frequency(self, member_id: str, claim_history: list) -> dict:
        thresholds = self.policy_terms.get("fraud_thresholds", {})
        same_day_limit = thresholds.get("same_day_claims_limit", 2)
        monthly_limit = thresholds.get("monthly_claims_limit", 6)
        prompt = f"""Given claim history for member {member_id}, check:
- Are there more than {same_day_limit} claims on the same day?
- Are there more than {monthly_limit} claims in the same month?
Return JSON with: same_day_count (int), monthly_count (int), flagged (bool), detail (str)."""
        return await extract_json(prompt, json.dumps(claim_history, default=str))

    async def _check_amount_anomaly(self, claimed_amount: float, extracted_data: dict) -> dict:
        extracted_total = 0.0
        for doc_type, data in extracted_data.items():
            if isinstance(data, dict):
                for field in ("total_amount", "total"):
                    val = data.get(field)
                    if val:
                        extracted_total += float(val)
                        break
        discrepancy = abs(claimed_amount - extracted_total) if extracted_total else 0
        return {
            "matches": discrepancy < 0.01 * claimed_amount if claimed_amount else True,
            "discrepancy": round(discrepancy, 2),
            "detail": f"Claimed: ₹{claimed_amount}, Extracted total: ₹{extracted_total}, Diff: ₹{discrepancy:.2f}",
        }

    async def _check_duplicate(self, claim_type: str, claimed_amount: float, claim_history: list) -> dict:
        for c in claim_history:
            if c.get("type") == claim_type and abs(c.get("amount", 0) - claimed_amount) < 0.01 * claimed_amount:
                return {"is_duplicate": True, "matched_claim_id": c.get("id"), "detail": "Duplicate claim detected"}
        return {"is_duplicate": False, "matched_claim_id": None, "detail": "No duplicate found"}

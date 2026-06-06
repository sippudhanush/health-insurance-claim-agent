import json
import logging
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from services.llm_client import extract_json

logger = logging.getLogger("plum.agent.policy")

SYSTEM_PROMPT = """You are a policy compliance agent for health insurance claims.
You have the full policy terms and extracted claim data.
Run every applicable rule check using tools. Return a trace of every check.
Be precise about amounts — apply sub-limits, co-pay, and network discounts correctly."""


class PolicyCheckerAgent(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str, policy_terms: dict):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_waiting_period",
                    "description": "Check if waiting period has been served for this member",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "join_date": {"type": "string"},
                            "treatment_date": {"type": "string"},
                            "diagnosis": {"type": "string"},
                        },
                        "required": ["join_date", "treatment_date", "diagnosis"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_sub_limit",
                    "description": "Check if claimed amount is within category sub-limit",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_type": {"type": "string"},
                            "claimed_amount": {"type": "number"},
                        },
                        "required": ["claim_type", "claimed_amount"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_exclusions",
                    "description": "Check if diagnosis or procedures are excluded",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "diagnosis": {"type": "string"},
                            "procedures": {"type": "string"},
                        },
                        "required": ["diagnosis", "procedures"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_pre_auth",
                    "description": "Check if pre-authorization is required",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_type": {"type": "string"},
                            "amount": {"type": "number"},
                            "has_pre_auth": {"type": "boolean"},
                        },
                        "required": ["claim_type", "amount", "has_pre_auth"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_copay",
                    "description": "Calculate co-pay and insurer payment",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_type": {"type": "string"},
                            "approved_amount": {"type": "number"},
                            "is_network_hospital": {"type": "boolean"},
                        },
                        "required": ["claim_type", "approved_amount", "is_network_hospital"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_network_hospital",
                    "description": "Check if hospital is in network",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hospital_name": {"type": "string"},
                        },
                        "required": ["hospital_name"],
                    },
                },
            },
        ]
        super().__init__(client, model, SYSTEM_PROMPT, tools)
        self.policy_terms = policy_terms
        self.register_tool("check_waiting_period", self._check_waiting_period)
        self.register_tool("check_sub_limit", self._check_sub_limit)
        self.register_tool("check_exclusions", self._check_exclusions)
        self.register_tool("check_pre_auth", self._check_pre_auth)
        self.register_tool("check_copay", self._check_copay)
        self.register_tool("check_network_hospital", self._check_network_hospital)

    async def _check_waiting_period(self, join_date: str, treatment_date: str, diagnosis: str) -> dict:
        prompt = """You are a policy waiting period checker. Given the policy waiting period rules,
a member's join date, treatment date, and diagnosis, determine if the waiting period has been served.
Return JSON with: passed (bool), waiting_days_required (int), days_served (int), detail (str)."""
        content = json.dumps({
            "join_date": join_date,
            "treatment_date": treatment_date,
            "diagnosis": diagnosis,
            "policy_waiting_periods": self.policy_terms.get("waiting_periods", {}),
        })
        return await extract_json(prompt, content)

    async def _check_sub_limit(self, claim_type: str, claimed_amount: float) -> dict:
        category_config = self.policy_terms.get("opd_categories", {}).get(claim_type.lower(), {})
        sub_limit = category_config.get("sub_limit")
        if sub_limit and claimed_amount > sub_limit:
            return {
                "passed": False,
                "sub_limit": sub_limit,
                "approved_amount": sub_limit,
                "detail": f"Claim ₹{claimed_amount} exceeds sub-limit of ₹{sub_limit}. Capped at ₹{sub_limit}.",
            }
        return {
            "passed": True,
            "sub_limit": sub_limit,
            "approved_amount": claimed_amount,
            "detail": f"Within sub-limit of ₹{sub_limit}" if sub_limit else "No sub-limit applies",
        }

    async def _check_exclusions(self, diagnosis: str, procedures: str) -> dict:
        exclusions = self.policy_terms.get("exclusions", {})
        all_excluded = exclusions.get("conditions", [])
        text = (diagnosis + " " + procedures).lower()
        for ex in all_excluded:
            if ex.lower() in text:
                return {"passed": False, "matched_exclusion": ex, "detail": f"Matches excluded condition: {ex}"}
        return {"passed": True, "matched_exclusion": None, "detail": "No exclusions matched"}

    async def _check_pre_auth(self, claim_type: str, amount: float, has_pre_auth: bool) -> dict:
        category_config = self.policy_terms.get("opd_categories", {}).get(claim_type.lower(), {})
        threshold = category_config.get("pre_auth_threshold")
        if threshold and amount > threshold and not has_pre_auth:
            return {
                "passed": False,
                "required": True,
                "threshold": threshold,
                "detail": f"Pre-authorization required for ₹{amount} (threshold ₹{threshold})",
            }
        return {"passed": True, "required": False, "threshold": threshold, "detail": "No pre-auth required"}

    async def _check_copay(self, claim_type: str, approved_amount: float, is_network_hospital: bool) -> dict:
        category_config = self.policy_terms.get("opd_categories", {}).get(claim_type.lower(), {})
        copay_percent = category_config.get("copay_percent", 0)
        discount_percent = category_config.get("network_discount_percent", 0) if is_network_hospital else 0
        after_discount = approved_amount * (1 - discount_percent / 100)
        copay_amount = after_discount * copay_percent / 100
        insurer_pays = after_discount - copay_amount
        return {
            "copay_percent": copay_percent,
            "copay_amount": round(copay_amount, 2),
            "insurer_pays": round(insurer_pays, 2),
            "detail": f"Network discount: {discount_percent}%, Copay: {copay_percent}%",
        }

    async def _check_network_hospital(self, hospital_name: str) -> dict:
        network = self.policy_terms.get("network_hospitals", [])
        is_network = any(h.lower() in hospital_name.lower() or hospital_name.lower() in h.lower() for h in network)
        return {"is_network": is_network, "discount_percent": "varies by category"}

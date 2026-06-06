from sqlalchemy.ext.asyncio import AsyncSession
from core.tool import Tool
from services.llm_client import groq_client
from models import PolicyCheck
import json


POLICY_SYSTEM_PROMPT = """You are a policy evaluation agent for health insurance claims. Your job is to evaluate a claim against the full policy terms and make coverage decisions.

You will receive:
1. Full policy_terms.json content
2. Claim details (member_id, category, claimed_amount, treatment_date, hospital_name, ytd_claims)
3. Extracted document content (diagnosis, medicines, line items, tests, etc.)
4. Member details from the policy

You must evaluate ALL of these checks:

1. **COVERAGE**: Is the claim category covered by the policy? Check opd_categories.{category}.covered.

2. **WAITING PERIODS**: Check the member's join_date against treatment_date. 
   - Must pass initial_waiting_period_days
   - Check specific_conditions based on diagnosis (diabetes, hypertension, etc.)

3. **EXCLUSIONS**: Check diagnosis and treatment text against the exclusion conditions list and category-specific exclusions.

4. **PRE-AUTHORIZATION**: Check if the treatment/procedure requires pre-auth. Look at pre_authorization.required_for and any category-specific thresholds.

5. **PER-CLAIM LIMIT**: Check if claimed_amount exceeds coverage.per_claim_limit.

6. **SUB-LIMIT**: Check if claimed_amount exceeds the category's sub_limit.

7. **APPROVED AMOUNT**: If eligible, calculate the approved amount:
   - If hospital is in network_hospitals, apply network_discount_percent
   - Apply copay_percent to get the final approved amount

Return a JSON object with:
{
  "eligible": true/false,
  "approved_amount_estimate": <number>,
  "copay_percent": <number>,
  "network_discount_percent": <number>,
  "rejection_reasons": ["REASON1", "REASON2"],
  "checks": [
    {
      "check_name": "coverage" or "waiting_period" or "exclusions" or "pre_auth" or "per_claim_limit" or "sub_limit",
      "status": "PASSED" or "FAILED" or "WARNING",
      "details": { ... explanation }
    }
  ],
  "breakdown_details": {
    "original": <claimed_amount>,
    "network_discount": "20%" or null,
    "after_discount": <number> or null,
    "copay": "10%" or null,
    "copay_amount": <number> or null,
    "approved_amount": <number>
  }
}

Be thorough. Use the policy terms exactly as provided. If eligible is false, provide clear rejection reasons."""


class EvaluatePolicyTool(Tool):
    def __init__(self, db: AsyncSession | None = None, policy_terms: dict | None = None):
        self.db = db
        self.policy_terms = policy_terms

    @property
    def name(self) -> str:
        return "evaluate_policy"

    @property
    def description(self) -> str:
        return "Evaluate a claim against policy terms using an LLM. Checks coverage, waiting periods, exclusions, pre-auth, limits, and calculates approved amount."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "member_id": {"type": "string"},
                "category": {"type": "string"},
                "claimed_amount": {"type": "number"},
                "treatment_date": {"type": "string"},
                "hospital_name": {"type": "string"},
                "extracted_docs": {"type": "array", "items": {"type": "object"}},
                "ytd_claims_amount": {"type": "number"},
            },
            "required": ["claim_id", "member_id", "category", "claimed_amount", "treatment_date"],
        }

    async def run(
        self,
        claim_id: str,
        member_id: str,
        category: str,
        claimed_amount: float,
        treatment_date: str,
        hospital_name: str | None = None,
        extracted_docs: list[dict] | None = None,
        ytd_claims_amount: float | None = None,
    ) -> dict:
        member_info = None
        if self.policy_terms:
            for m in self.policy_terms.get("members", []):
                if m.get("member_id") == member_id:
                    member_info = m
                    break

        user_content = json.dumps({
            "claim": {
                "claim_id": claim_id,
                "member_id": member_id,
                "category": category,
                "claimed_amount": claimed_amount,
                "treatment_date": treatment_date,
                "hospital_name": hospital_name,
                "ytd_claims_amount": ytd_claims_amount,
            },
            "extracted_documents": extracted_docs or [],
            "member_info": member_info,
            "policy_terms": self.policy_terms,
        }, indent=2, default=str)

        result = await groq_client.structured_extract(POLICY_SYSTEM_PROMPT, user_content, max_tokens=4000)

        if self.db:
            for check in result.get("checks", []):
                self.db.add(PolicyCheck(
                    claim_id=claim_id,
                    check_name=check["check_name"],
                    status=check["status"],
                    details=check.get("details"),
                ))
            await self.db.flush()

        return result

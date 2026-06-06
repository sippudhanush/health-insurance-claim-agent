import asyncio
import json
from health_insurance_agent.claim_agent import process_claim


async def main():
    result = await process_claim({
        "claim_id": "CLM_DEMO_001",
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "hospital_name": "City Clinic",
        "documents": [],
        "claims_history": [],
    })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

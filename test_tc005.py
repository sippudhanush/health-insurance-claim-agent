"""Test TC005 — Waiting Period for Diabetes (rejected)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC005_DIR = Path(__file__).resolve().parent / "tests" / "TC005_Waiting_Period_-_Diabetes"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC005_TEST",
        "member_id": "EMP005",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-15",
        "claimed_amount": 3000,
        "hospital_name": "Unity Diabetes Centre",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F009",
                "filename": "F009.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC005_DIR / "F009.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F010",
                "filename": "F010.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC005_DIR / "F010.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("TC005: Waiting Period — Diabetes")
    print("EMP005 | CONSULTATION | Rs.3000 | Joined 2024-09-01, Treatment 2024-10-15")
    print("Diabetes specific waiting period: 90 days → expected REJECTED")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result.get("decision") == "REJECTED":
        reasons = result.get("rejection_reasons", [])
        if any("waiting" in r.lower() for r in reasons):
            print(f"\n✓ REJECTED — Waiting period correctly identified")
        else:
            print(f"\n✗ REJECTED but reasons: {reasons}")
    else:
        print(f"\n✗ Expected REJECTED, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

"""Test full claim pipeline on TC004 — clean consultation, full approval."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC004_DIR = Path(__file__).resolve().parent / "tests" / "TC004_Clean_Consultation_-_Full_Approval"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC004_TEST",
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "hospital_name": "Fortis Healthcare",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F007",
                "filename": "F007.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC004_DIR / "F007.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F008",
                "filename": "F008.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC004_DIR / "F008.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC004: Clean Consultation — Full Approval")
    print("EMP001 | CONSULTATION | Rs.1500 | Fortis Healthcare (network) → 20% discount + 10% co-pay → expected Rs.1080")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result.get("decision") == "APPROVED":
        print(f"\n✓ APPROVED — Amount: {result.get('approved_amount')}")
    else:
        print(f"\n✗ Expected APPROVED, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

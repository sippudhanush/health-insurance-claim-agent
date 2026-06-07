"""Test TC007 — MRI Without Pre-Authorization (rejected)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401
from health_insurance_agent.claim_agent import process_claim

TC007_DIR = Path(__file__).resolve().parent / "tests" / "TC007_MRI_Without_Pre-Authorization"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC007_TEST",
        "member_id": "EMP007",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "DIAGNOSTIC",
        "treatment_date": "2024-10-20",
        "claimed_amount": 15000,
        "hospital_name": "Apollo Hospitals",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F012",
                "filename": "F012.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC007_DIR / "F012.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F013",
                "filename": "F013.pdf",
                "doc_type_hint": "LAB_REPORT",
                "base64_content": encode_file(TC007_DIR / "F013.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F014",
                "filename": "F014.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC007_DIR / "F014.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("TC007: MRI Without Pre-Authorization")
    print("EMP007 | DIAGNOSTIC | Rs.15000 | MRI > ₹10,000 threshold")
    print("Pre-auth required for MRI > ₹10,000 → expected REJECTED")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result.get("decision") == "REJECTED":
        reasons = result.get("rejection_reasons", [])
        if any("pre-auth" in r.lower() or "pre_auth" in r.lower() for r in reasons):
            print(f"\n✓ REJECTED — Pre-authorisation correctly identified")
        else:
            print(f"\n✗ REJECTED but reasons: {reasons}")
    else:
        print(f"\n✗ Expected REJECTED, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

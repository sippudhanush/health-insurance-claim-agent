"""Test TC008 — Per-Claim Limit Exceeded (rejected)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401
from health_insurance_agent.claim_agent import process_claim

TC008_DIR = Path(__file__).resolve().parent / "tests" / "TC008_Per-Claim_Limit_Exceeded"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC008_TEST",
        "member_id": "EMP003",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-20",
        "claimed_amount": 7500,
        "hospital_name": "Max Healthcare",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F015",
                "filename": "F015.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC008_DIR / "F015.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F016",
                "filename": "F016.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC008_DIR / "F016.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("TC008: Per-Claim Limit Exceeded")
    print("EMP003 | CONSULTATION | Rs.7500 | Per-claim limit is Rs.5000")
    print("Claimed amount exceeds per-claim limit → expected REJECTED")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result.get("decision") == "REJECTED":
        reasons = result.get("rejection_reasons", [])
        if any("per-claim" in r.lower() or "per_claim" in r.lower() for r in reasons):
            print(f"\n✓ REJECTED — Per-claim limit correctly identified")
        else:
            print(f"\n✗ REJECTED but reasons: {reasons}")
    else:
        print(f"\n✗ Expected REJECTED, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

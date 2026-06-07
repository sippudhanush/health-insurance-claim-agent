"""Test TC006 — Dental Partial Approval — Cosmetic Exclusion."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401
from health_insurance_agent.claim_agent import process_claim

TC006_DIR = Path(__file__).resolve().parent / "tests" / "TC006_Dental_Partial_Approval_-_Cosmetic_Exclusion"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC006_TEST",
        "member_id": "EMP002",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "DENTAL",
        "treatment_date": "2024-10-15",
        "claimed_amount": 12000,
        "hospital_name": "Smile Dental Clinic",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F011",
                "filename": "F011.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC006_DIR / "F011.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "DENTAL_REPORT",
                "filename": "DENTAL_REPORT.pdf",
                "doc_type_hint": "DENTAL_REPORT",
                "base64_content": encode_file(TC006_DIR / "DENTAL_REPORT.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("TC006: Dental Partial Approval — Cosmetic Exclusion")
    print("EMP002 | DENTAL | Rs.12000 | Root Canal (8000) + Teeth Whitening (4000)")
    print("Teeth Whitening is cosmetic → excluded → expected PARTIAL 8000")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    decision = result.get("decision")
    amt = result.get("approved_amount")
    if decision == "PARTIAL" and amt == 8000:
        print(f"\n✓ PARTIAL — Amount: {amt}")
    elif decision == "PARTIAL":
        print(f"\n✓ PARTIAL but amount {amt} (expected 8000)")
    else:
        print(f"\n✗ Expected PARTIAL, got {decision}")


if __name__ == "__main__":
    asyncio.run(main())

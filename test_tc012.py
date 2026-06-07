"""Test full claim pipeline on TC012 — Excluded Treatment (bariatric/obesity)."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC012_DIR = Path(__file__).resolve().parent / "tests" / "TC012_Excluded_Treatment"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC012_TEST",
        "member_id": "EMP009",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-18",
        "claimed_amount": 8000,
        "hospital_name": "Wellness Hospital, Kolkata",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F023",
                "filename": "F023.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC012_DIR / "F023.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F024",
                "filename": "F024.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC012_DIR / "F024.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC012: Excluded Treatment")
    print("EMP009 | CONSULTATION | Rs.8,000 | Obesity treatment (excluded)")
    print("Expected: REJECTED — EXCLUDED_CONDITION (bariatric/obesity)")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    decision = result.get("decision")
    reasons = result.get("rejection_reasons", [])
    confidence = result.get("confidence_score", 0)
    reasons_lower = " ".join(reasons).lower()
    has_exclusion = any(kw in reasons_lower for kw in ["exclud", "obes", "bariatric", "weight loss"])

    passed = decision == "REJECTED" and has_exclusion
    status = "\xe2\x9c\x93 PASS" if passed else "\xe2\x9c\x97 FAIL"
    print(f"\n{status} | Decision: {decision} | Confidence: {confidence:.2f} | Expected: REJECTED + excluded condition")
    if not passed:
        print(f"  Reasons: {reasons}")
    else:
        print(f"  Reasons: {reasons[0] if reasons else 'N/A'}")


if __name__ == "__main__":
    asyncio.run(main())

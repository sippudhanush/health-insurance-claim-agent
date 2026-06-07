"""Test full claim pipeline on TC010 — Network Hospital Discount Applied."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC010_DIR = Path(__file__).resolve().parent / "tests" / "TC010_Network_Hospital_-_Discount_Applied"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC010_TEST",
        "member_id": "EMP010",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-03",
        "claimed_amount": 4500,
        "hospital_name": "Apollo Hospitals",
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F019",
                "filename": "F019.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC010_DIR / "F019.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F020",
                "filename": "F020.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC010_DIR / "F020.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC010: Network Hospital — Discount Applied")
    print("EMP010 | CONSULTATION | Rs.4500 | Apollo Hospitals (network)")
    print("20% discount first → 10% co-pay → expected Rs.3240")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    exp_amt = 3240
    if result.get("decision") == "APPROVED" and result.get("approved_amount") == exp_amt:
        print(f"\n✓ APPROVED — Amount: {result.get('approved_amount')} (expected Rs.{exp_amt})")
    elif result.get("decision") == "APPROVED":
        print(f"\n✓ APPROVED but amount {result.get('approved_amount')} (expected Rs.{exp_amt})")
    else:
        print(f"\n✗ Expected APPROVED, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

"""Test TC009 — Fraud Signal: Multiple Same-Day Claims → MANUAL_REVIEW."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401
from health_insurance_agent.claim_agent import process_claim

TC009_DIR = Path(__file__).resolve().parent / "tests" / "TC009_Fraud_Signal_-_Multiple_Same-Day_Claims"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC009_TEST",
        "member_id": "EMP008",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-20",
        "claimed_amount": 4800,
        "hospital_name": "Apollo Hospitals",
        "claims_history": [
            {"claim_id": "HIST_001", "treatment_date": "2024-10-20", "claimed_amount": 2000, "status": "APPROVED"},
            {"claim_id": "HIST_002", "treatment_date": "2024-10-20", "claimed_amount": 1500, "status": "APPROVED"},
            {"claim_id": "HIST_003", "treatment_date": "2024-10-20", "claimed_amount": 3000, "status": "APPROVED"},
        ],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F017",
                "filename": "F017.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC009_DIR / "F017.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F018",
                "filename": "F018.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC009_DIR / "F018.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("TC009: Fraud Signal — Multiple Same-Day Claims")
    print("EMP008 (Ravi Menon) | CONSULTATION | Rs.4800 | 3 same-day claims in history")
    print("Same-day total = 4 (3 history + 1 current), limit = 2")
    print("4-2 = 2 >= 2 → manual_review_required = true → expected MANUAL_REVIEW")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if result.get("decision") == "MANUAL_REVIEW":
        print(f"\n✓ MANUAL_REVIEW — Fraud signal correctly triggered")
    else:
        print(f"\n✗ Expected MANUAL_REVIEW, got {result.get('decision')}")


if __name__ == "__main__":
    asyncio.run(main())

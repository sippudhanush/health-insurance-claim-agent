"""Test full claim pipeline on TC002 — unreadable document."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC002_DIR = Path(__file__).resolve().parent / "tests" / "TC002_Unreadable_Document"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC002_TEST",
        "member_id": "EMP004",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "PHARMACY",
        "treatment_date": "2024-10-25",
        "claimed_amount": 800,
        "hospital_name": None,
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F003",
                "filename": "prescription.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC002_DIR / "prescription.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F004",
                "filename": "blurry_bill.pdf",
                "doc_type_hint": "PHARMACY_BILL",
                "base64_content": encode_file(TC002_DIR / "blurry_bill.pdf"),
                "quality": "UNREADABLE",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC002: Unreadable Document")
    print("PHARMACY claim with valid prescription + unreadable pharmacy bill")
    print("Expected: detect unreadable bill, ask for re-upload (not reject)")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())

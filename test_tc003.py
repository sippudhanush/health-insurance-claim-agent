"""Test full claim pipeline on TC003 — docs belong to different patients."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC003_DIR = Path(__file__).resolve().parent / "tests" / "TC003_Documents_Belong_to_Different_Patients"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC003_TEST",
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "hospital_name": None,
        "claims_history": [],
        "simulate_component_failure": False,
        "documents": [
            {
                "transaction_uuid": "F005",
                "filename": "prescription_rajesh.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC003_DIR / "prescription_rajesh.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F006",
                "filename": "bill_arjun.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC003_DIR / "bill_arjun.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC003: Documents Belong to Different Patients")
    print("CONSULTATION claim — prescription (Rajesh Kumar) vs bill (Arjun Mehta)")
    print("Expected: detect mismatch, surface names, stop before decision")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())

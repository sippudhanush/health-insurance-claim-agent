"""Test full claim pipeline on TC001 — should stop at document verifier."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.claim_agent import process_claim

TC001_DIR = Path(__file__).resolve().parent / "Plum Assignment - 12-04-2026" / "test_case_inputs" / "TC001_Wrong_Document_Uploaded"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC001_TEST",
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
                "transaction_uuid": "F001",
                "filename": "dr_sharma_prescription.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC001_DIR / "dr_sharma_prescription.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F002",
                "filename": "another_prescription.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC001_DIR / "another_prescription.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC001: Wrong Document Uploaded")
    print("CONSULTATION requires PRESCRIPTION + HOSPITAL_BILL")
    print("Uploaded: 2 x PRESCRIPTION → should stop at verification")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())

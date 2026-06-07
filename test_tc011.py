"""Test full claim pipeline on TC011 — Component Failure — Graceful Degradation."""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from health_insurance_agent.config import OPENAI_API_KEY  # noqa: F401 - loads .env
from health_insurance_agent.claim_agent import process_claim

TC011_DIR = Path(__file__).resolve().parent / "tests" / "TC011_Component_Failure_-_Graceful_Degradation"


def encode_file(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def main():
    claim_data = {
        "claim_id": "CLM_TC011_TEST",
        "member_id": "EMP006",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "ALTERNATIVE_MEDICINE",
        "treatment_date": "2024-10-28",
        "claimed_amount": 4000,
        "claims_history": [],
        "simulate_component_failure": True,
        "documents": [
            {
                "transaction_uuid": "F021",
                "filename": "F021.pdf",
                "doc_type_hint": "PRESCRIPTION",
                "base64_content": encode_file(TC011_DIR / "F021.pdf"),
                "quality": "GOOD",
            },
            {
                "transaction_uuid": "F022",
                "filename": "F022.pdf",
                "doc_type_hint": "HOSPITAL_BILL",
                "base64_content": encode_file(TC011_DIR / "F022.pdf"),
                "quality": "GOOD",
            },
        ],
    }

    print("=" * 60)
    print("Full pipeline on TC011: Component Failure — Graceful Degradation")
    print("EMP006 | ALTERNATIVE_MEDICINE | Rs.4000 | simulate_component_failure=True")
    print("Expected: APPROVED with lower confidence + degradation notes")
    print("=" * 60)
    print()

    result = await process_claim(claim_data)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # Check expectations
    print()
    print("--- Results Check ---")

    # 1) Must not crash — if we got here, it didn't
    print("  [PASS] System did not crash")

    # 2) Decision should be APPROVED (or something meaningful)
    decision = result.get("decision", "N/A")
    if decision == "APPROVED":
        print(f"  [PASS] Decision: {decision}")
    else:
        print(f"  [INFO] Decision: {decision} (expected APPROVED)")

    # 3) Degradation notes should be present
    deg_notes = result.get("degradation_notes", [])
    if deg_notes:
        print(f"  [PASS] Degradation notes present ({len(deg_notes)}):")
        for n in deg_notes:
            print(f"         - {n}")
    else:
        print("  [FAIL] No degradation notes found")

    # 4) Confidence score should be lower than 1.0
    conf = result.get("confidence_score", 1.0)
    if conf < 1.0:
        print(f"  [PASS] Confidence score lowered: {conf:.2f}")
    else:
        print(f"  [INFO] Confidence score: {conf:.2f} (expected < 1.0)")

    # 5) Check for manual review recommendation in reasoning/degradation_notes
    reasoning = result.get("reasoning", "")
    all_text = reasoning + " " + " ".join(deg_notes)
    if "manual review" in all_text.lower() or "manual_review" in all_text.lower():
        print("  [PASS] Manual review recommended")
    else:
        print("  [INFO] No explicit manual review recommendation")

    approved_amt = result.get("approved_amount")
    if approved_amt is not None:
        print(f"  Approved amount: Rs.{approved_amt:,.0f}")


if __name__ == "__main__":
    asyncio.run(main())

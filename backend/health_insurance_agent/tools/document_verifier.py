from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional

from agents import Agent, ModelSettings, Runner, function_tool
from pydantic import BaseModel

from .file_handlers import build_content_items

logger = logging.getLogger("doc_verifier")

DEFAULT_MODEL = os.getenv("CLAIM_AGENT_MODEL", "gpt-4o-mini")


class DocVerificationItem(BaseModel):
    transaction_uuid: str
    valid: bool
    detected_type: Optional[str] = None
    vision_classification: Optional[str] = None
    type_mismatch: Optional[bool] = None
    quality: Optional[str] = None
    patient_name: Optional[str] = None
    error: Optional[str] = None


class DocVerificationOut(BaseModel):
    transactions: List[DocVerificationItem]
    overall_valid: bool
    missing_docs: List[str] = []
    wrong_docs: List[str] = []


SYSTEM_INSTRUCTIONS = """\
You are DocumentVerifier. Examine each document image provided and classify it.

The first text message tells you the claim_category, required document types,
and optional document types. You MUST use this information.

Step 1 — Classify each document:
- Examine the image and classify the actual document type.
- Choose the single best match from: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT,
  PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT, DIAGNOSTIC_REPORT.
- Compare the actual type with the stated doc_type_hint. If they differ,
  set type_mismatch=true and an error like:
  "You uploaded a {actual_type} but labelled it as {doc_type_hint}."
- Assess readability: "GOOD" if text is legible, "UNREADABLE" if not.
- Extract the patient name visible on the document.
- If quality is "UNREADABLE", mark valid=false with error:
  "The document {filename} is unreadable. Please re-upload a clearer copy."

Step 2 — Verify against requirements (CRITICAL):
- The first text message states the claim_category, required[], and optional[].
- Check that ALL required document types are present among the actual classifications.
- If any required type is missing, add it to missing_docs.
- If a document's type is NOT in required[] or optional[], add its filename to wrong_docs.
- If patient names differ across documents, add an error on each mismatched doc.

Step 3 — Set overall_valid:
- overall_valid = true ONLY if ALL individual documents are valid
  AND every required type is present (missing_docs must be empty).
- Otherwise overall_valid = false.

Return the output matching DocVerificationOut schema exactly.
"""


@function_tool
async def verify_documents(items: Any) -> str:
    return await _run_verification(items)


async def _run_verification(items: Any) -> str:
    if isinstance(items, str):
        raw = json.loads(items)
    elif isinstance(items, dict):
        raw = items
    else:
        raw = {}
    doc_list: list[dict] = raw.get("documents", [])

    claim_category = raw.get("claim_category") or raw.get("claim", {}).get("claim_category", "")
    policy_terms = raw.get("policy_terms", {})
    doc_reqs = policy_terms.get("document_requirements", {}).get(claim_category, {})

    content_items: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "=== CLAIM REQUIREMENTS ===\n"
                f"Claim category: {claim_category}\n"
                f"Required document types: {json.dumps(doc_reqs.get('required', []), ensure_ascii=False)}\n"
                f"Optional document types: {json.dumps(doc_reqs.get('optional', []), ensure_ascii=False)}\n"
                "=== END REQUIREMENTS ===\n\n"
                "Classify each document image below."
            ),
        },
    ]

    for doc in doc_list:
        label = (
            f"Document: {doc.get('transaction_uuid', 'unknown')} — "
            f"stated type: {doc.get('doc_type_hint', 'UNKNOWN')}, "
            f"filename: {doc.get('filename', 'unknown')}"
        )
        file_id = doc.get("file_id", "")
        base64_content = doc.get("base64_content", "")

        if file_id:
            items = await build_content_items(file_id=file_id, prefix_text=label)
        elif base64_content:
            items = await build_content_items(base64_content=base64_content, prefix_text=label)
        else:
            continue
        content_items.extend(items)

    if len(content_items) <= 1:
        return json.dumps({
            "transactions": [],
            "overall_valid": False,
            "missing_docs": [],
            "wrong_docs": [],
        })

    agent = Agent(
        name="DocumentVerifier",
        instructions=SYSTEM_INSTRUCTIONS,
        model=DEFAULT_MODEL,
        output_type=DocVerificationOut,
        model_settings=ModelSettings(temperature=0.1),
    )

    message = {"type": "message", "role": "user", "content": content_items}
    result = await Runner.run(agent, [message])
    verification = result.final_output_as(DocVerificationOut)

    return verification.model_dump_json()

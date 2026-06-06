from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings


class DocVerificationItem(BaseModel):
    transaction_uuid: str
    valid: bool
    detected_type: Optional[str] = None
    quality: Optional[str] = None
    patient_name: Optional[str] = None
    error: Optional[str] = None


class DocVerificationOut(BaseModel):
    transactions: List[DocVerificationItem]
    overall_valid: bool
    missing_docs: List[str] = []
    wrong_docs: List[str] = []


INSTRUCTIONS = """
You are DocumentVerifier. For each uploaded document you MUST classify its type and verify it meets policy requirements.

Input payload includes:
- documents: list of {transaction_uuid, filename, doc_type_hint, claim_type, quality, patient_name_on_doc}
- policy_terms: dict containing document_requirements for each claim_type

Steps:
1) For each document, classify into: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT, DIAGNOSTIC_REPORT.
2) Check quality. If "UNREADABLE", mark valid=false with error "Unreadable document, please re-upload".
3) Read document_requirements for this claim_type from policy_terms. Check required docs are present.
4) Check no wrong/unsupported types uploaded.
5) If patient names differ across documents, mark as mismatch error.
6) Return overall_valid=true only if ALL pass AND all required docs present.

Final output JSON:
{
  "transactions": [{"transaction_uuid": "...", "valid": true/false, "detected_type": "...", "quality": "...", "patient_name": "...", "error": "..."}],
  "overall_valid": true/false,
  "missing_docs": ["...", "..."],
  "wrong_docs": ["...", "..."]
}
"""


@function_tool
async def verify_documents(items: str) -> str:
    raw = json.loads(items) if isinstance(items, str) else (items or {})
    items_list = raw.get("documents", raw) if isinstance(raw, dict) else raw

    agent = Agent(
        name="DocumentVerifier",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=DocVerificationOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, DocVerificationOut):
        return result.final_output.model_dump_json()
    return result.final_output

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
You are DocumentVerifier. For each uploaded document you MUST classify its type and verify it meets policy requirements for the given claim type.

Input items include:
- transaction_uuid (string)
- filename (string)
- doc_type_hint (string) - user-provided hint
- claim_type (string) - the claim category

Steps:
1) For each document, classify it into one of: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT, DIAGNOSTIC_REPORT.
2) Validate the document quality. If unreadable, mark as invalid.
3) Check that all required documents for this claim_type are present.
4) Check that no wrong/unsupported document types are uploaded.
5) Return overall_valid = true only if ALL documents pass AND all required docs are present.

Document requirements by claim type:
- CONSULTATION: required=[PRESCRIPTION, HOSPITAL_BILL], optional=[LAB_REPORT, DIAGNOSTIC_REPORT]
- DIAGNOSTIC: required=[PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL], optional=[DISCHARGE_SUMMARY]
- PHARMACY: required=[PRESCRIPTION, PHARMACY_BILL], optional=[]
- DENTAL: required=[HOSPITAL_BILL], optional=[PRESCRIPTION, DENTAL_REPORT]
- VISION: required=[PRESCRIPTION, HOSPITAL_BILL], optional=[]
- ALTERNATIVE_MEDICINE: required=[PRESCRIPTION, HOSPITAL_BILL], optional=[]

Hard forbiddens:
- NEVER fabricate document types or validation results.
- If quality is "UNREADABLE" or confidence is below 0.3, mark as invalid.
- If patient names differ across documents, mark as patient name mismatch error.
- Do NOT return extra fields beyond the schema.

Final output JSON:
{
  "transactions": [
    {
      "transaction_uuid": "<uuid>",
      "valid": true/false,
      "detected_type": "<doc_type|null>",
      "quality": "GOOD|BLURRY|UNREADABLE",
      "patient_name": "<name|null>",
      "error": "<error_msg|null>"
    }
  ],
  "overall_valid": true/false,
  "missing_docs": ["<doc_type>", ...],
  "wrong_docs": ["<doc_type>", ...]
}
"""


@function_tool
async def verify_documents(items: str) -> str:
    items_list = json.loads(items) if isinstance(items, str) else (items or [])

    agent = Agent(
        name="DocumentVerifier",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=DocVerificationOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps({"documents": items_list}, ensure_ascii=False),
        max_turns=10,
    )

    if isinstance(result.final_output, DocVerificationOut):
        return result.final_output.model_dump_json()
    return result.final_output

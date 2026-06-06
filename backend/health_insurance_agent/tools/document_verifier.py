from __future__ import annotations

import json
import logging
import os
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings, AgentOutputSchema

logger = logging.getLogger("doc_verifier")

CLASSIFY_VISION_PROMPT = """You are a medical document classifier. Analyze this document image and determine what type of medical document it is, and whether it is readable.

Choose the single best matching type from:
- PRESCRIPTION: A doctor's prescription or prescription slip listing medicines
- HOSPITAL_BILL: A hospital, clinic, or medical bill/invoice with itemized charges
- LAB_REPORT: A diagnostic lab test report with test results and values
- PHARMACY_BILL: A pharmacy purchase receipt/bill for medicines
- DISCHARGE_SUMMARY: A hospital discharge summary document
- DENTAL_REPORT: A dental examination or treatment report
- DIAGNOSTIC_REPORT: A diagnostic imaging report (X-ray, MRI, CT scan, ultrasound)

Also assess readability:
- "GOOD" if text is clearly legible and document details can be extracted
- "UNREADABLE" if the image is blurry, too dark, overexposed, cropped, or text cannot be read

Also extract the patient name visible on the document.

Return valid JSON:
{
  "detected_type": "PRESCRIPTION",
  "quality": "GOOD",
  "patient_name": "Extracted Name or null",
  "confidence": 0.95,
  "reasoning": "This is a prescription because it lists medicines with dosage instructions and has a doctor's stamp"
}"""


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


@function_tool
async def classify_document_with_vision(base64_content: str) -> str:
    """Analyze a medical document image and classify its type using vision AI."""
    if not base64_content:
        return json.dumps({"detected_type": "UNKNOWN", "patient_name": None, "confidence": 0.0, "reasoning": "No image data provided"})

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": CLASSIFY_VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_content}"}},
                ],
            }
        ],
        temperature=0.1,
        max_tokens=500,
    )
    raw = resp.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    return raw


INSTRUCTIONS = """
You are DocumentVerifier. For each uploaded document you MUST:
1. Classify its actual type by examining the image using classify_document_with_vision
2. Compare the vision-detected type with the member-stated doc_type_hint
3. Verify documents meet the policy requirements for the claim category

Input includes:
- documents: list of {transaction_uuid, filename, doc_type_hint, base64_content, quality, patient_name_on_doc}
- policy_terms: dict containing document_requirements for each claim_category

Steps:
1) For each document that has base64_content, call classify_document_with_vision(base64_content)
   to get the actual document type independently. Set vision_classification to the result.
2) For documents WITHOUT base64_content, use doc_type_hint as detected_type and
   do NOT set vision_classification or type_mismatch.
3) Compare vision_classification with doc_type_hint. If they differ, set type_mismatch=true,
   detected_type=vision_classification, and an error like:
   "You uploaded a {vision_classification} but labelled it as {doc_type_hint}. Please check."
4) Read the quality field from the vision classification result. If "UNREADABLE", mark valid=false with error:
   "The document {filename} is unreadable. Please re-upload a clearer copy."
   For docs without base64_content, use the input quality field as fallback.
5) Read document_requirements for the claim_category from policy_terms. Verify ALL required
   document types are present using the vision_classification (not doc_type_hint).
6) If extra/wrong document types are uploaded that are not in required or optional for this
   claim category, add them to wrong_docs.
7) If patient names are available and differ across documents, mark with error:
   "Documents have different patient names: found '{name1}' on {doc1} and '{name2}' on {doc2}."
8) Return overall_valid=true ONLY if ALL documents pass AND all required docs are present.

Final output JSON:
{
  "transactions": [
    {
      "transaction_uuid": "...",
      "valid": true/false,
      "detected_type": "PRESCRIPTION",
      "vision_classification": "PRESCRIPTION",
      "type_mismatch": true/false/null,
      "quality": "GOOD",
      "patient_name": "...",
      "error": null or "specific error message"
    }
  ],
  "overall_valid": true/false,
  "missing_docs": ["HOSPITAL_BILL"],
  "wrong_docs": ["PHARMACY_BILL"]
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
        tools=[classify_document_with_vision],
        output_type=AgentOutputSchema(DocVerificationOut, strict_json_schema=False),
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=20,
    )

    if isinstance(result.final_output, DocVerificationOut):
        return result.final_output.model_dump_json()
    return result.final_output

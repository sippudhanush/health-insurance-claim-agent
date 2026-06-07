from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from agents import Agent, ModelSettings, Runner, function_tool
from pydantic import BaseModel, ConfigDict

from health_insurance_agent.config import CLAIM_AGENT_MODEL
from .file_handlers import build_content_items

logger = logging.getLogger("doc_verifier")


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class DocVerificationItem(BaseModel):
    transaction_uuid: str
    valid: bool
    detected_type: Optional[str] = None
    vision_classification: Optional[str] = None
    type_mismatch: Optional[bool] = None
    quality: Optional[str] = None
    patient_name: Optional[str] = None
    error: Optional[str] = None


class DocBatchOutput(BaseModel):
    transactions: List[DocVerificationItem]


class DocVerificationOut(BaseModel):
    transactions: List[DocVerificationItem]
    required_docs: List[str] = []
    optional_docs: List[str] = []


CLASSIFY_INSTRUCTION = """\
Classify each document image below.

For every document, output a single DocVerificationItem with:
- transaction_uuid: the document's uuid
- detected_type: one of PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT, DIAGNOSTIC_REPORT
- type_mismatch: true if the actual document type differs from the stated type
- patient_name: the patient name visible on the document (or null if unclear)
- valid: false only if UNREADABLE or the document content doesn't match its expected type
- error: brief explanation if valid=false, else null

Documents to classify (in order):
"""


@function_tool(strict_mode=False)
async def verify_documents(items: ToolInput) -> str:
    return await _run_verification(items)


async def _run_verification(items: ToolInput) -> str:
    raw = items.model_dump() if not isinstance(items, dict) else items
    doc_list: list[dict] = raw.get("documents", [])

    claim_category = raw.get("claim_category") or raw.get("claim", {}).get("claim_category", "")
    policy_terms = raw.get("policy_terms", {})
    doc_reqs = policy_terms.get("document_requirements", {}).get(claim_category, {})
    required = doc_reqs.get("required", [])
    optional = doc_reqs.get("optional", [])

    doc_agent = Agent(
        name="DocClassifier",
        instructions=CLASSIFY_INSTRUCTION,
        model=CLAIM_AGENT_MODEL,
        output_type=DocBatchOutput,
        model_settings=ModelSettings(temperature=0.1),
    )

    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": CLASSIFY_INSTRUCTION},
    ]
    doc_descriptions: list[str] = []
    for doc in doc_list:
        tid = doc.get("transaction_uuid", "unknown")
        hint = doc.get("doc_type_hint", "UNKNOWN")
        fname = doc.get("filename", "unknown")
        doc_descriptions.append(f"  - {fname} (uuid: {tid}, stated type: {hint})")

        file_id = doc.get("file_id", "")
        base64_content = doc.get("base64_content", "")
        if file_id:
            content.extend(await build_content_items(file_id=file_id))
        elif base64_content:
            content.extend(await build_content_items(base64_content=base64_content))

    content[0] = {
        "type": "input_text",
        "text": CLASSIFY_INSTRUCTION + "\n".join(doc_descriptions),
    }

    msg = {"type": "message", "role": "user", "content": content}
    result = await Runner.run(doc_agent, [msg])
    batch = result.final_output_as(DocBatchOutput)
    transactions = batch.transactions

    out = DocVerificationOut(
        transactions=transactions,
        required_docs=required,
        optional_docs=optional,
    )
    return out.model_dump_json()

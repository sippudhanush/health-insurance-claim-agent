from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional

from agents import Agent, ModelSettings, Runner, function_tool
from pydantic import BaseModel, ConfigDict

from .file_handlers import build_content_items

logger = logging.getLogger("doc_extractor")

DEFAULT_MODEL = os.getenv("CLAIM_AGENT_MODEL", "gpt-4o-mini")


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class MedicineOut(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    duration: Optional[str] = None


class LineItemOut(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None


class TestOut(BaseModel):
    name: Optional[str] = None
    result: Optional[str] = None
    unit: Optional[str] = None
    normal_range: Optional[str] = None


class ExtractedDoc(BaseModel):
    transaction_uuid: str
    doc_type: str
    doctor_name: Optional[str] = None
    reg_no: Optional[str] = None
    patient_name: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    date: Optional[str] = None
    diagnosis: Optional[str] = None
    medicines: List[MedicineOut] = []
    tests_ordered: List[str] = []
    hospital_name: Optional[str] = None
    bill_no: Optional[str] = None
    line_items: List[LineItemOut] = []
    total_amount: Optional[float] = None
    lab_name: Optional[str] = None
    tests: List[TestOut] = []
    pharmacy_name: Optional[str] = None
    confidence: float = 1.0
    low_confidence_fields: List[str] = []


class ExtractionOut(BaseModel):
    documents: List[ExtractedDoc]


SYSTEM_INSTRUCTIONS = """\
You are a meticulous medical document extraction agent.
Examine each document image provided and extract all visible medical data.

Rules:
- Parse ONLY what is visibly printed on the document; do not invent values.
- Dates must be in YYYY-MM-DD format when confidently readable.
- Numbers are JSON numbers (not strings).
- If a field is not visible or cannot be confidently extracted, set it to null.
- For each document you process, return one ExtractedDoc entry.

Field mapping by document type:
- PRESCRIPTION → doctor_name, reg_no, patient_name, age, gender, date, diagnosis, medicines[], tests_ordered[]
- HOSPITAL_BILL → hospital_name, bill_no, date, patient_name, line_items[], total_amount
- LAB_REPORT → lab_name, patient_name, date, tests[] (each test: name, result, unit, normal_range)
- PHARMACY_BILL → pharmacy_name, date, patient_name, doctor_name, medicines[], total_amount
- DISCHARGE_SUMMARY → hospital_name, doctor_name, patient_name, date, diagnosis, medicines[], tests_ordered[], line_items[]
- DENTAL_REPORT → doctor_name, patient_name, date, diagnosis, line_items[], total_amount
- DIAGNOSTIC_REPORT → lab_name, patient_name, date, tests[] (each test: name, result, unit, normal_range)

For unreadable fields set to null, add the field name to low_confidence_fields.
Never fail an entire document because one field is unclear.
Set confidence between 0 and 1 reflecting overall extraction reliability.

Important — sign preservation:
Preserve the numeric sign exactly as printed for all numeric fields.
Never drop a visible minus sign and never convert a negative value into absolute positive.
"""


@function_tool(strict_mode=False)
async def extract_documents(items: ToolInput) -> str:
    raw = items.model_dump() if not isinstance(items, dict) else items
    doc_list: list[dict] = raw.get("documents", [])

    if raw.get("simulate_component_failure"):
        logger.warning("Simulating document extraction failure (degraded)")
        return json.dumps({
            "documents": [],
            "degradation_notes": ["Document extraction component failed (simulated)"],
        })

    content_items: list[dict[str, Any]] = [
        {"type": "input_text", "text": "Extract structured medical data from the documents below."},
    ]

    for doc in doc_list:
        label = (
            f"Document: {doc.get('transaction_uuid', 'unknown')} — "
            f"type: {doc.get('doc_type_hint', 'UNKNOWN')}"
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
            "documents": [],
            "degradation_notes": ["No documents with base64 content provided"],
        })

    agent = Agent(
        name="DocumentExtractor",
        instructions=SYSTEM_INSTRUCTIONS,
        model=DEFAULT_MODEL,
        output_type=ExtractionOut,
        model_settings=ModelSettings(temperature=0.1),
    )

    message = {"type": "message", "role": "user", "content": content_items}
    result = await Runner.run(agent, [message])
    extraction = result.final_output_as(ExtractionOut)

    return extraction.model_dump_json()

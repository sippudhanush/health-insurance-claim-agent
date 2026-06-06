from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings


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


PRESCRIPTION_PROMPT = """Extract all fields from this medical prescription image.
Return JSON with: doctor_name, reg_no, patient_name, age, gender, date,
diagnosis, medicines (array of {name, dosage, duration}),
tests_ordered (array of strings), confidence (0.0-1.0).
If any field is unreadable, set to null."""

HOSPITAL_BILL_PROMPT = """Extract all fields from this hospital bill image.
Return JSON with: hospital_name, bill_no, date, patient_name,
line_items (array of {description, amount}), total_amount, confidence (0.0-1.0)."""

LAB_REPORT_PROMPT = """Extract all fields from this lab report image.
Return JSON with: lab_name, patient_name, ref_doctor, sample_date, report_date,
tests (array of {name, result, unit, normal_range}), confidence (0.0-1.0)."""

PHARMACY_BILL_PROMPT = """Extract all fields from this pharmacy bill image.
Return JSON with: pharmacy_name, date, patient_name, doctor_name,
medicines (array of {name, batch, qty, amount}), total_amount, confidence (0.0-1.0)."""


INSTRUCTIONS = """
You are DocumentExtractor. Extract structured data from medical document images using vision AI.

Input items:
- transaction_uuid (string)
- doc_type (string) - type of document
- base64_content (string) - base64-encoded image

For each document, call the appropriate extraction tool based on doc_type:
- PRESCRIPTION -> extract_prescription
- HOSPITAL_BILL -> extract_hospital_bill
- LAB_REPORT -> extract_lab_report
- PHARMACY_BILL -> extract_pharmacy_bill

Rules:
- Extract every field you can.
- For unreadable fields set value to null and add to low_confidence_fields.
- Never fail the whole document because one field is unclear.
- Set confidence based on how clearly the information is visible.

Return ONLY the final JSON array of extracted documents.
"""


@function_tool
async def extract_documents(items: str) -> str:
    items_list = json.loads(items) if isinstance(items, str) else (items or [])

    agent = Agent(
        name="DocumentExtractor",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        output_type=ExtractionOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps({"documents": items_list}, ensure_ascii=False),
        max_turns=20,
    )

    if isinstance(result.final_output, ExtractionOut):
        return result.final_output.model_dump_json()
    return result.final_output

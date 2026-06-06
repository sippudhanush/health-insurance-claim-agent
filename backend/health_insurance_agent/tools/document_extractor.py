from __future__ import annotations

import json
from typing import List, Optional
from pydantic import BaseModel
from agents import Agent, Runner, function_tool, ModelSettings
from openai import AsyncOpenAI
import os
import logging

logger = logging.getLogger("doc_extractor")


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


EXTRACT_VISION_PROMPT = """Extract all fields from this medical document image.
Return ALL fields you can find in JSON. Set unreadable fields to null.
Add field names to low_confidence_fields if uncertain."""


INSTRUCTIONS = """
You are DocumentExtractor. Extract structured data from medical document images using vision AI.

Input:
- documents: list of {transaction_uuid, doc_type, base64_content}
- You have one tool: extract_with_vision(base64_content, doc_type)

For each document, call extract_with_vision which sends the image to OpenAI vision.
Merge results into the output schema based on doc_type:
- PRESCRIPTION → doctor_name, reg_no, patient_name, age, gender, date, diagnosis, medicines[], tests_ordered[]
- HOSPITAL_BILL → hospital_name, bill_no, date, patient_name, line_items[], total_amount
- LAB_REPORT → lab_name, patient_name, ref_doctor, sample_date, report_date, tests[]
- PHARMACY_BILL → pharmacy_name, date, patient_name, doctor_name, medicines[], total_amount

For unreadable fields set to null, add name to low_confidence_fields.
Never fail whole doc because one field is unclear.
"""


@function_tool
async def extract_with_vision(base64_content: str, doc_type: str) -> str:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_content}"}},
                ],
            }
        ],
        temperature=0.1,
    )
    raw = resp.choices[0].message.content or "{}"
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    return raw


@function_tool
async def extract_documents(items: str) -> str:
    raw = json.loads(items) if isinstance(items, str) else (items or {})
    items_list = raw.get("documents", raw) if isinstance(raw, dict) else raw

    if raw.get("simulate_component_failure"):
        logger.warning("Simulating document extraction failure (degraded)")
        return json.dumps({
            "documents": [],
            "degradation_notes": ["Document extraction component failed (simulated)"],
        })

    agent = Agent(
        name="DocumentExtractor",
        instructions=INSTRUCTIONS,
        model="gpt-4o-mini",
        tools=[extract_with_vision],
        output_type=ExtractionOut,
        model_settings=ModelSettings(reasoning={"effort": "low"}),
    )

    result = await Runner.run(
        agent,
        input=json.dumps(raw, ensure_ascii=False),
        max_turns=20,
    )

    if isinstance(result.final_output, ExtractionOut):
        return result.final_output.model_dump_json()
    return result.final_output

import json
import logging
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent

logger = logging.getLogger("plum.agent.extractor")

SYSTEM_PROMPT = """You are a medical document extraction agent specializing in Indian medical documents.
Documents may be handwritten, rubber-stamped, blurry, or phone photos.
Extract every field you can. For unreadable fields set value to null and add to
low_confidence_fields. Never fail the whole document because one field is unclear."""

EXTRACT_PRESCRIPTION_PROMPT = """Extract all fields from this medical prescription image.
Return JSON with: doctor_name, reg_no, patient_name, age, gender, date,
diagnosis, medicines (array of {name, dosage, duration}),
tests_ordered (array of strings), confidence (0.0-1.0).
If any field is unreadable, set to null."""

EXTRACT_HOSPITAL_BILL_PROMPT = """Extract all fields from this hospital bill image.
Return JSON with: hospital_name, bill_no, date, patient_name,
line_items (array of {description, amount}), total_amount, confidence (0.0-1.0)."""

EXTRACT_LAB_REPORT_PROMPT = """Extract all fields from this lab report image.
Return JSON with: lab_name, patient_name, ref_doctor, sample_date, report_date,
tests (array of {name, result, unit, normal_range}), confidence (0.0-1.0)."""

EXTRACT_PHARMACY_BILL_PROMPT = """Extract all fields from this pharmacy bill image.
Return JSON with: pharmacy_name, date, patient_name, doctor_name,
medicines (array of {name, batch, qty, amount}), total_amount, confidence (0.0-1.0)."""


class DocExtractorAgent(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str, vision_model: str):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "extract_prescription",
                    "description": "Extract structured data from a prescription document image",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base64_content": {"type": "string", "description": "Base64-encoded image content"},
                        },
                        "required": ["base64_content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_hospital_bill",
                    "description": "Extract structured data from a hospital bill image",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base64_content": {"type": "string"},
                        },
                        "required": ["base64_content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_lab_report",
                    "description": "Extract structured data from a lab report image",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base64_content": {"type": "string"},
                        },
                        "required": ["base64_content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_pharmacy_bill",
                    "description": "Extract structured data from a pharmacy bill image",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "base64_content": {"type": "string"},
                        },
                        "required": ["base64_content"],
                    },
                },
            },
        ]
        super().__init__(client, model, SYSTEM_PROMPT, tools)
        self.vision_model = vision_model
        self.register_tool("extract_prescription", self._call_vision_prescription)
        self.register_tool("extract_hospital_bill", self._call_vision_hospital_bill)
        self.register_tool("extract_lab_report", self._call_vision_lab_report)
        self.register_tool("extract_pharmacy_bill", self._call_vision_pharmacy_bill)

    async def _call_vision(self, base64_content: str, prompt: str) -> dict:
        resp = await self.client.chat.completions.create(
            model=self.vision_model,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_content}"}},
                ]},
            ],
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or "{}"
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])
        return json.loads(raw)

    async def _call_vision_prescription(self, base64_content: str) -> dict:
        return await self._call_vision(base64_content, EXTRACT_PRESCRIPTION_PROMPT)

    async def _call_vision_hospital_bill(self, base64_content: str) -> dict:
        return await self._call_vision(base64_content, EXTRACT_HOSPITAL_BILL_PROMPT)

    async def _call_vision_lab_report(self, base64_content: str) -> dict:
        return await self._call_vision(base64_content, EXTRACT_LAB_REPORT_PROMPT)

    async def _call_vision_pharmacy_bill(self, base64_content: str) -> dict:
        return await self._call_vision(base64_content, EXTRACT_PHARMACY_BILL_PROMPT)

import json
from httpx import AsyncClient
from core.config import settings

GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"

LIGHT_EXTRACTION_PROMPT = """You are a medical document analyzer. Given a document (or its description), extract:
1. document_type: One of [PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT]
2. quality: One of [GOOD, PARTIAL, UNREADABLE]
3. patient_name: The patient's full name (or null if not found)
4. confidence: A score 0.0 to 1.0 for how confident you are in the extraction

Return ONLY valid JSON with keys: detected_type, quality, patient_name, confidence.
If the document is a handwritten prescription, blurry photo, or has text quality issues, set quality accordingly."""

DEEP_EXTRACTION_PROMPT = """You are a medical document data extractor. Extract ALL structured information from this medical document.

For PRESCRIPTION, extract:
- doctor_name, doctor_registration, patient_name, date, diagnosis, medicines (list with name,dosage,duration), tests_ordered

For HOSPITAL_BILL, extract:
- hospital_name, hospital_address, bill_number, date, patient_name, line_items (list with description,amount), total, gst

For LAB_REPORT, extract:
- lab_name, patient_name, date, test_name, results (list with name,value,unit,normal_range), remarks

For PHARMACY_BILL, extract:
- pharmacy_name, bill_number, date, patient_name, medicines (list with name,batch,expiry,qty,mrp,amount), total

Return ONLY valid JSON with the extracted fields. If fields are missing or unreadable, set them to null."""


class GroqClient:
    def __init__(self):
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model
        self.client = AsyncClient(timeout=30.0)

    async def _call(self, prompt: str, content: str) -> str:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not configured")
        resp = await self.client.post(
            GROQ_API_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content},
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def light_extract(self, file_description: str) -> dict:
        raw = await self._call(LIGHT_EXTRACTION_PROMPT, file_description)
        return json.loads(raw)

    async def deep_extract(self, doc_type: str, file_content: str) -> dict:
        prompt = DEEP_EXTRACTION_PROMPT + f"\n\nDocument type: {doc_type}"
        raw = await self._call(prompt, file_content)
        return json.loads(raw)


groq_client = GroqClient()

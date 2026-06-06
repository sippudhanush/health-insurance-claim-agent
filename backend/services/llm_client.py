import json
import logging
from httpx import AsyncClient
from core.config import settings
from services.langfuse_client import langfuse

logger = logging.getLogger("plum.llm")

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

    async def _call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 2000,
    ) -> dict:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not configured")
        content_len = sum(len(m.get("content", "") or "") for m in messages)
        logger.info("Groq API request — model=%s messages=%d content_len=%d", self.model, len(messages), content_len)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        start = __import__("time").time()
        resp = await self.client.post(
            GROQ_API_BASE,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        elapsed = __import__("time").time() - start
        choice = data["choices"][0]["message"]
        logger.info(
            "Groq API response — elapsed=%.2fs tokens=%d tool_calls=%s",
            elapsed,
            data.get("usage", {}).get("total_tokens", 0),
            bool(choice.get("tool_calls")),
        )
        return choice

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 2000) -> dict:
        return await self._call(messages, tools=tools, max_tokens=max_tokens)

    async def _call_prompt(self, prompt: str, content: str, max_tokens: int = 2000) -> str:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]
        choice = await self._call(messages, max_tokens=max_tokens)
        return choice.get("content", "")

    async def structured_extract(self, system_prompt: str, user_content: str, max_tokens: int = 4000) -> dict:
        raw = await self._call_prompt(system_prompt, user_content, max_tokens=max_tokens)
        raw_stripped = raw.strip()
        if raw_stripped.startswith("```"):
            lines = raw_stripped.split("\n")
            raw_stripped = "\n".join(lines[1:-1])
        return json.loads(raw_stripped)

    async def light_extract(self, file_description: str, trace_id: str | None = None) -> dict:
        span = langfuse.span(
            name="light_extract",
            trace_id=trace_id,
            input={"file_description": file_description},
        ) if trace_id and langfuse else None
        try:
            raw = await self._call_prompt(LIGHT_EXTRACTION_PROMPT, file_description)
            result = json.loads(raw)
            logger.info("light_extract parsed — type=%s confidence=%s", result.get("detected_type"), result.get("confidence"))
            if span:
                span.end(output=result)
            return result
        except json.JSONDecodeError as e:
            logger.error("light_extract JSON parse failed — raw=%s error=%s", raw[:200], e)
            if span:
                span.end(level="ERROR", output={"error": str(e)})
            raise
        except Exception as e:
            logger.error("light_extract failed — error=%s", e)
            if span:
                span.end(level="ERROR", output={"error": str(e)})
            raise

    async def deep_extract(self, doc_type: str, file_content: str, trace_id: str | None = None) -> dict:
        prompt = DEEP_EXTRACTION_PROMPT + f"\n\nDocument type: {doc_type}"
        span = langfuse.span(
            name="deep_extract",
            trace_id=trace_id,
            input={"doc_type": doc_type, "file_content": file_content},
        ) if trace_id and langfuse else None
        try:
            raw = await self._call_prompt(prompt, file_content)
            result = json.loads(raw)
            logger.info("deep_extract parsed — doc_type=%s fields=%s", doc_type, list(result.keys()))
            if span:
                span.end(output=result)
            return result
        except json.JSONDecodeError as e:
            logger.error("deep_extract JSON parse failed — raw=%s error=%s", raw[:200], e)
            if span:
                span.end(level="ERROR", output={"error": str(e)})
            raise
        except Exception as e:
            logger.error("deep_extract failed — doc_type=%s error=%s", doc_type, e)
            if span:
                span.end(level="ERROR", output={"error": str(e)})
            raise


groq_client = GroqClient()

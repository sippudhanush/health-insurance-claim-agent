import json
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are a document verification agent for an Indian health insurance company.
You will receive a claim type and a list of uploaded document filenames.
Classify each document and verify the required set is present per policy rules.
If anything is wrong, return a specific actionable error message — never generic."""


class DocVerifierAgent(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str, policy_terms: dict):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "classify_document",
                    "description": "Determine the document type from filename and user-provided hint",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "doc_type_hint": {"type": "string"},
                        },
                        "required": ["filename", "doc_type_hint"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "validate_document_set",
                    "description": "Check that the required documents are present for this claim type",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_type": {"type": "string"},
                            "classified_docs": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["claim_type", "classified_docs"],
                    },
                },
            },
        ]
        super().__init__(client, model, SYSTEM_PROMPT, tools)
        self.policy_terms = policy_terms
        self.register_tool("classify_document", self._classify_document)
        self.register_tool("validate_document_set", self._validate_document_set)

    async def _classify_document(self, filename: str, doc_type_hint: str) -> dict:
        return {"doc_type": doc_type_hint, "confidence": 0.9}

    async def _validate_document_set(self, claim_type: str, classified_docs: list) -> dict:
        reqs = self.policy_terms.get("document_requirements", {}).get(claim_type, {})
        required = reqs.get("required", [])
        optional = reqs.get("optional", [])
        all_allowed = required + optional
        present_types = [d.get("doc_type") for d in classified_docs if d.get("doc_type")]

        missing = [r for r in required if r not in present_types]
        wrong = [d.get("doc_type") for d in classified_docs if d.get("doc_type") not in all_allowed]

        missing = [m for m in missing if m is not None]
        wrong = [w for w in wrong if w is not None]

        if missing or wrong:
            parts = []
            if missing:
                parts.append(f"Missing required document(s): {', '.join(missing)}")
            if wrong:
                parts.append(f"Wrong document type(s): {', '.join(wrong)}")
            return {
                "valid": False,
                "missing": missing,
                "wrong": wrong,
                "message": ". ".join(parts),
            }
        return {"valid": True, "missing": [], "wrong": [], "message": "All required documents present"}

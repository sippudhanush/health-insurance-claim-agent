import json
from core.tool import Tool
from services.llm_client import groq_client


VALIDATION_SYSTEM_PROMPT = """You are a document validation agent for health insurance claims. Your job is to validate uploaded documents against claim requirements.

You will receive:
1. Claim category
2. Extracted document details (file_id, detected_type, quality, patient_name_on_doc, confidence)
3. Policy document requirements (what documents are required/optional for this category)
4. Member details from policy (name, member_id)

You must check:
1. **Document types**: Each uploaded document must be a required or optional type for this category. If a document type is not in the required or optional list, flag it as WRONG_DOCUMENT_TYPE.
2. **Missing documents**: All required document types must be present. If any are missing, flag MISSING_REQUIRED_DOCUMENT.
3. **Document quality**: If a document has quality "UNREADABLE", flag UNREADABLE_DOCUMENT.
4. **Patient name match**: The patient_name_on_doc from extracted documents should match the member name from policy. If multiple documents have different patient names, flag PATIENT_NAME_MISMATCH.

Return a JSON object with:
{
  "valid": true/false,
  "errors": [
    {
      "code": "UNREADABLE_DOCUMENT" or "WRONG_DOCUMENT_TYPE" or "MISSING_REQUIRED_DOCUMENT" or "PATIENT_NAME_MISMATCH",
      "message": "Clear, specific error message telling the member exactly what is wrong and how to fix it",
      "details": { ... }
    }
  ]
}

If valid is true, errors should be an empty array. Be thorough but practical - use the provided data to make your judgment."""


class ValidateDocumentsTool(Tool):
    def __init__(self, db=None, policy_terms: dict | None = None):
        self.db = db
        self.policy_terms = policy_terms

    @property
    def name(self) -> str:
        return "validate_documents"

    @property
    def description(self) -> str:
        return "Validate extracted documents against the claim category requirements using the policy terms."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The claim category (e.g. CONSULTATION, DIAGNOSTIC, etc.)",
                },
                "documents": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of extracted documents with detected_type, quality, patient_name_on_doc, file_id",
                },
                "member_id": {
                    "type": "string",
                    "description": "Member ID for looking up in policy terms",
                },
            },
            "required": ["category", "documents", "member_id"],
        }

    async def run(self, category: str, documents: list[dict], member_id: str | None = None) -> dict:
        doc_requirements = {}
        member_info = None

        if self.policy_terms:
            doc_requirements = self.policy_terms.get("document_requirements", {}).get(category, {})
            for m in self.policy_terms.get("members", []):
                if m.get("member_id") == member_id:
                    member_info = m
                    break

        user_content = json.dumps({
            "category": category,
            "documents": documents,
            "document_requirements": doc_requirements,
            "member_info": member_info,
        }, indent=2)

        result = await groq_client.structured_extract(VALIDATION_SYSTEM_PROMPT, user_content)
        return {
            "valid": result.get("valid", False),
            "errors": result.get("errors", []),
            "error_count": len(result.get("errors", [])),
        }

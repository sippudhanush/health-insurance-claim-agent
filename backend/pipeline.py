import json
import base64
import os
from pathlib import Path
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from agents.doc_verifier import DocVerifierAgent
from agents.doc_extractor import DocExtractorAgent
from agents.policy_checker import PolicyCheckerAgent
from agents.fraud_detector import FraudDetectorAgent
from agents.decision_maker import DecisionMakerAgent

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/files"))
LOCAL_UPLOAD_DIR = Path(__file__).parent.parent / "files"

OPENAI_BASE_URL = "https://api.openai.com/v1"
AGENT_MODEL = "gpt-4o-mini"
VISION_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are a health insurance claims processing orchestrator. You have 5 tools to process a claim. Call them in the right order.

Tools:
1. verify_documents(claim_type, documents) - Check uploaded docs against policy requirements. Call FIRST.
2. extract_documents(documents_with_base64) - Extract structured data from document images using vision AI.
3. check_policy(claim_type, member_id, claimed_amount, treatment_date, hospital_name, extracted_data) - Evaluate against policy terms.
4. detect_fraud(member_id, claimed_amount, claim_history) - Analyse fraud risk.
5. decide_claim(claim, verification_result, extraction_result, policy_result, fraud_result) - Make final decision. Call LAST.

Rules:
- Call verify_documents first. If valid=false, STOP — no further tools.
- After verification, call extract_documents.
- Then call check_policy and detect_fraud.
- Finally call decide_claim with everything. Return its output."""


def _get_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=OPENAI_BASE_URL)


def _read_file_base64(file_id: str) -> str | None:
    for d in (UPLOAD_DIR, LOCAL_UPLOAD_DIR):
        p = d / file_id
        if p.exists():
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return None


class Orchestrator(BaseAgent):
    def __init__(self, client: AsyncOpenAI, model: str, vision_model: str, policy_terms: dict):
        self.policy_terms = policy_terms
        self._sub_client = client
        self._sub_model = model
        self._vision_model = vision_model

        tools = [
            {"type": "function", "function": {
                "name": "verify_documents",
                "description": "Verify uploaded documents match claim category requirements",
                "parameters": {"type": "object", "properties": {
                    "claim_type": {"type": "string"},
                    "documents": {"type": "array", "items": {"type": "object"}},
                }, "required": ["claim_type", "documents"]},
            }},
            {"type": "function", "function": {
                "name": "extract_documents",
                "description": "Extract structured data from document images using vision AI",
                "parameters": {"type": "object", "properties": {
                    "documents_with_base64": {"type": "array", "items": {"type": "object"}},
                }, "required": ["documents_with_base64"]},
            }},
            {"type": "function", "function": {
                "name": "check_policy",
                "description": "Evaluate claim against policy terms",
                "parameters": {"type": "object", "properties": {
                    "claim_type": {"type": "string"},
                    "member_id": {"type": "string"},
                    "claimed_amount": {"type": "number"},
                    "treatment_date": {"type": "string"},
                    "hospital_name": {"type": "string"},
                    "extracted_data": {"type": "object"},
                }, "required": ["claim_type", "member_id", "claimed_amount", "treatment_date"]},
            }},
            {"type": "function", "function": {
                "name": "detect_fraud",
                "description": "Analyse the claim for fraud signals",
                "parameters": {"type": "object", "properties": {
                    "member_id": {"type": "string"},
                    "claimed_amount": {"type": "number"},
                    "claim_history": {"type": "array", "items": {"type": "object"}},
                }, "required": ["member_id", "claimed_amount"]},
            }},
            {"type": "function", "function": {
                "name": "decide_claim",
                "description": "Make the final claim decision. Call LAST with all results.",
                "parameters": {"type": "object", "properties": {
                    "claim": {"type": "object"},
                    "verification_result": {"type": "object"},
                    "extraction_result": {"type": "object"},
                    "policy_result": {"type": "object"},
                    "fraud_result": {"type": "object"},
                }, "required": ["claim", "verification_result", "extraction_result", "policy_result", "fraud_result"]},
            }},
        ]

        super().__init__(client, model, SYSTEM_PROMPT, tools)
        self.register_tool("verify_documents", self._verify_documents)
        self.register_tool("extract_documents", self._extract_documents)
        self.register_tool("check_policy", self._check_policy)
        self.register_tool("detect_fraud", self._detect_fraud)
        self.register_tool("decide_claim", self._decide_claim)

    async def _verify_documents(self, claim_type: str, documents: list) -> dict:
        a = DocVerifierAgent(self._sub_client, self._sub_model, self.policy_terms)
        return await a.run([{"role": "user", "content": json.dumps({"claim_type": claim_type, "documents": documents})}])

    async def _extract_documents(self, documents_with_base64: list) -> dict:
        a = DocExtractorAgent(self._sub_client, self._sub_model, self._vision_model)
        return await a.run([{"role": "user", "content": json.dumps({"documents": documents_with_base64})}])

    async def _check_policy(self, claim_type, member_id, claimed_amount, treatment_date, hospital_name=None, extracted_data=None):
        member = next((m for m in self.policy_terms.get("members", []) if m.get("member_id") == member_id), None)
        a = PolicyCheckerAgent(self._sub_client, self._sub_model, self.policy_terms)
        return await a.run([{"role": "user", "content": json.dumps({
            "extracted_data": extracted_data or {},
            "member": member or {},
            "claim_type": claim_type,
            "claimed_amount": claimed_amount,
            "treatment_date": treatment_date,
            "policy": self.policy_terms,
        })}])

    async def _detect_fraud(self, member_id: str, claimed_amount: float, claim_history: list | None = None) -> dict:
        a = FraudDetectorAgent(self._sub_client, self._sub_model, self.policy_terms)
        return await a.run([{"role": "user", "content": json.dumps({
            "extracted_data": {},
            "claimed_amount": claimed_amount,
            "member_id": member_id,
            "claim_history": claim_history or [],
            "policy": {"fraud_thresholds": self.policy_terms.get("fraud_thresholds", {})},
        })}])

    async def _decide_claim(self, claim, verification_result, extraction_result, policy_result, fraud_result):
        a = DecisionMakerAgent(self._sub_client, self._sub_model)
        r = await a.run([{"role": "user", "content": json.dumps({
            "claim": claim,
            "agent1": verification_result,
            "agent2": extraction_result,
            "agent3": policy_result,
            "agent4": fraud_result,
        })}])
        r["trace"] = {
            "document_verification": verification_result,
            "extraction": extraction_result,
            "policy_checks": policy_result,
            "fraud_check": fraud_result,
            "decision_reasoning": r.get("trace", {}).get("decision_reasoning", ""),
        }
        return r


async def run_pipeline(claim_data: dict, policy_terms: dict, api_key: str):
    client = _get_client(api_key)
    orch = Orchestrator(client, AGENT_MODEL, VISION_MODEL, policy_terms)

    claim_id = claim_data.get("claim_id", "")
    yield {"event": "start", "data": json.dumps({"claim_id": claim_id, "status": "PROCESSING"})}

    docs_with_b64 = []
    for d in claim_data.get("documents", []):
        b64 = _read_file_base64(d.get("file_id", ""))
        if b64:
            docs_with_b64.append({
                "filename": d.get("file_name", d.get("file_id")),
                "base64_content": b64,
                "doc_type": d.get("actual_type", "UNKNOWN"),
            })

    msg = {
        "claim": {
            "claim_id": claim_id,
            "member_id": claim_data.get("member_id"),
            "policy_id": claim_data.get("policy_id"),
            "claim_category": claim_data.get("claim_category"),
            "treatment_date": str(claim_data.get("treatment_date", "")),
            "claimed_amount": claim_data.get("claimed_amount", 0),
            "hospital_name": claim_data.get("hospital_name"),
        },
        "documents": [
            {"filename": d.get("file_name", d.get("file_id")), "doc_type_hint": d.get("actual_type", "UNKNOWN")}
            for d in claim_data.get("documents", [])
        ],
        "documents_with_base64": docs_with_b64,
        "claim_history": claim_data.get("claims_history", []),
    }

    result = await orch.run([{"role": "user", "content": json.dumps(msg)}])

    if result.get("status") == "STOPPED" or (result.get("decision") and result.get("decision") in ("ERROR", "DEGRADED")):
        yield {"event": "error", "data": json.dumps({
            "code": "DOCUMENT_ERROR",
            "message": result.get("error", "Processing failed"),
            "claim_id": claim_id,
        })}
        yield {"event": "done", "data": "{}"}
        return

    yield {"event": "result", "data": json.dumps(result)}
    yield {"event": "done", "data": "{}"}

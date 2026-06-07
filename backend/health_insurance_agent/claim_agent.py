from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel
from agents import Agent, Runner, ModelSettings, RunConfig, trace, AgentOutputSchema
from agents.tracing import add_trace_processor
from agents.tracing.processors import ConsoleSpanExporter, BatchTraceProcessor
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from health_insurance_agent.tools.document_verifier import verify_documents
from health_insurance_agent.tools.document_extractor import extract_documents
from health_insurance_agent.tools.policy_checker import check_policy
from health_insurance_agent.tools.fraud_detector import detect_fraud
from health_insurance_agent.tools.decision_maker import decide_claim
from health_insurance_agent.tools.file_handlers import (
    upload_file,
    delete_uploaded_file,
    is_pdf,
)

logger = logging.getLogger("claim_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(h)
logger.setLevel(os.getenv("CLAIM_AGENT_LOG_LEVEL", "INFO"))

AGENT_MODEL = os.getenv("CLAIM_AGENT_MODEL", "gpt-4o-mini")
POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "policy_terms.json"

_TRACING_SETUP = False


def _ensure_tracing() -> None:
    global _TRACING_SETUP
    if not _TRACING_SETUP:
        add_trace_processor(BatchTraceProcessor(ConsoleSpanExporter()))
        _TRACING_SETUP = True
        logger.info("ConsoleSpanExporter registered — traces will print to terminal")


def load_policy_terms() -> dict:
    with open(POLICY_PATH) as f:
        return json.load(f)


class ClaimOut(BaseModel):
    claim_id: str
    decision: str
    approved_amount: float | None = None
    confidence_score: float
    rejection_reasons: list[str] = []
    reasoning: str = ""
    line_item_breakdown: list[dict] | None = None
    degradation_notes: list[str] = []
    trace: dict = {}


INSTRUCTIONS = """
You are HealthInsuranceClaimProcessor. Use tools to process health insurance claims.

CRITICAL RULE — STOP ON VERIFICATION FAILURE:
You MUST call verify_documents FIRST. If its output has overall_valid=false,
you MUST STOP immediately. Do NOT call any other tool.
Return the error with missing_docs and wrong_docs info to the user.

Tools:
- verify_documents(items) — Call FIRST. Pass {documents, policy_terms}.
  If overall_valid=false → STOP. Return error immediately.
- extract_documents(items) — Call ONLY if verification passed.
- check_policy(items) — Call ONLY if extraction succeeded.
- detect_fraud(items) — Call ONLY if policy check passed.
- decide_claim(items) — Call LAST. Return its output.

Important — Graceful Degradation:
- If any tool call fails (returns an error), do NOT crash the pipeline.
- Log what failed and continue with whatever data you have.
- Pass the failure information downstream so the decision maker can lower confidence.
- If simulate_component_failure is true in the input, one tool may fail intentionally — handle it gracefully.

Data flow (only proceed if prior step succeeded):
1) verify_documents: pass {documents, policy_terms}. If overall_valid=false → STOP. Return error.
2) extract_documents: pass {documents, policy_terms}.
3) check_policy: pass {claim, member, extracted_data, policy_terms}.
4) detect_fraud: pass {member_id, claimed_amount, extracted_data, claim_history, policy_terms}.
5) decide_claim: pass ALL outputs from steps 1-4 + claim + policy_terms. Call LAST.

The input payload contains a "policy_terms" key with the full policy configuration.
Use it everywhere — do NOT rely on hardcoded values.

Return ONLY the final output from decide_claim.
"""


def build_agent() -> Agent:
    instr = f"{RECOMMENDED_PROMPT_PREFIX}\n{INSTRUCTIONS}"
    return Agent(
        name="HealthInsuranceClaimProcessor",
        instructions=instr,
        model=AGENT_MODEL,
        model_settings=ModelSettings(temperature=0.1),
        tools=[
            verify_documents,
            extract_documents,
            check_policy,
            detect_fraud,
            decide_claim,
        ],
        output_type=AgentOutputSchema(ClaimOut, strict_json_schema=False),
    )


async def process_claim(claim_data: Dict[str, Any]) -> Dict[str, Any]:
    start = time.time()
    claim_id = claim_data.get("claim_id", "unknown")

    policy_terms = load_policy_terms()

    member = None
    for m in policy_terms.get("members", []):
        if m.get("member_id") == claim_data.get("member_id"):
            member = m
            break

    documents = list(claim_data.get("documents", []))
    uploaded_file_ids: list[str] = []

    try:
        for doc in documents:
            b64 = doc.get("base64_content", "")
            if b64 and is_pdf(b64):
                raw = base64.b64decode(b64) if isinstance(b64, str) else b64
                fid = await upload_file(raw)
                uploaded_file_ids.append(fid)
                doc["file_id"] = fid

        claim_category = claim_data.get("claim_category", "")
        payload: dict = {
            "claim": {
                "claim_id": claim_id,
                "member_id": claim_data.get("member_id"),
                "policy_id": claim_data.get("policy_id"),
                "claim_category": claim_category,
                "treatment_date": claim_data.get("treatment_date"),
                "claimed_amount": claim_data.get("claimed_amount"),
                "hospital_name": claim_data.get("hospital_name"),
            },
            "claim_category": claim_category,
            "documents": documents,
            "claim_history": claim_data.get("claims_history", []),
            "member": member or {},
            "policy_terms": policy_terms,
        }

        if claim_data.get("simulate_component_failure"):
            payload["simulate_component_failure"] = True

        _ensure_tracing()

        with trace("Health Insurance Claim Processing", group_id=claim_id):
            logger.info("Processing claim: %s", claim_id)

            agent = build_agent()
            try:
                res = await Runner.run(
                    agent,
                    input=json.dumps(payload, ensure_ascii=False),
                    max_turns=15,
                    run_config=RunConfig(workflow_name="Health Insurance Claim Agent"),
                )
                result = getattr(res, "final_output", res)
            except Exception as e:
                logger.error("Agent pipeline failed for %s: %s", claim_id, e)
                result = {
                    "claim_id": claim_id,
                    "decision": "MANUAL_REVIEW",
                    "approved_amount": None,
                    "confidence_score": 0.3,
                    "rejection_reasons": ["SYSTEM_ERROR"],
                    "reasoning": f"Pipeline error: {e}",
                    "line_item_breakdown": None,
                    "degradation_notes": [f"Pipeline failed: {e}"],
                }

    finally:
        for fid in uploaded_file_ids:
            await delete_uploaded_file(fid)

    if isinstance(result, ClaimOut):
        output = result.model_dump()
    elif isinstance(result, dict):
        output = result
    else:
        output = {"claim_id": claim_id, "decision": "ERROR", "confidence_score": 0.0}

    output.setdefault("claim_id", claim_id)
    output.setdefault("line_item_breakdown", None)
    output.setdefault("degradation_notes", [])
    logger.info("Claim %s done in %.2fs → %s", claim_id, time.time() - start, output.get("decision"))
    return output

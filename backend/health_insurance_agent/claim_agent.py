from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel
from agents import Agent, Runner, ModelSettings, RunConfig, trace, AgentOutputSchema
from agents.tracing import add_trace_processor
from agents.tracing.processors import ConsoleSpanExporter, BatchTraceProcessor
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from health_insurance_agent.config import CLAIM_AGENT_MODEL, CLAIM_AGENT_LOG_LEVEL
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
logger.setLevel(CLAIM_AGENT_LOG_LEVEL)
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

CRITICAL RULE — YOU MUST DECIDE IF REQUIRED DOCUMENTS ARE MISSING:
The "member" key in your input contains the member's name (member.name).
Use this to check that all documents actually belong to the member.

Call verify_documents FIRST. It classifies each uploaded document and returns:
- transactions: list of classified docs with detected_type, valid, error
- required_docs: list of document types needed for this claim category
- optional_docs: list of optional document types

Look at the "policy_terms" (already in your input) to find what's required based on the claim category.
Then compare the detected_type from each transaction against the required_docs list.

Check each transaction's "valid" and "quality" fields:

A) If a required document type is COMPLETELY MISSING (not found among the detected types
   at all) → STOP immediately. Do NOT call any other tool. Construct a ClaimOut with:
   - decision: "REJECTED"
   - claim_id: from the input
   - confidence_score: 1.0
   - rejection_reasons: ["MISSING_DOCUMENTS"]
   - reasoning: clearly state which required document types are missing and what was uploaded instead

B) If a required document type IS present but the specific doc is invalid/unreadable
   (valid=false, quality="unreadable"/"poor") → STOP immediately.
   Do NOT call any other tool. Construct a ClaimOut with:
   - decision: "MANUAL_REVIEW"
   - claim_id: from the input
   - confidence_score: 0.5
   - rejection_reasons: ["UNREADABLE_DOCUMENT"]
   - reasoning: clearly state which document is unreadable and ask the member to re-upload it.
     Do NOT reject the claim outright — this is a re-upload request, not a denial.

C) After checking doc types, compare the "patient_name" field across ALL verified
   transactions. Also compare each patient_name against the member's name (from
   the "member" key in your input). If any patient_name differs → STOP immediately.
   Do NOT call any other tool. Construct a ClaimOut with:
   - decision: "MANUAL_REVIEW"
   - claim_id: from the input
   - confidence_score: 0.6
   - rejection_reasons: ["PATIENT_NAME_MISMATCH"]
   - reasoning: For each document that has a different patient_name, state:
       "The document '<filename>' shows patient name '<name_on_doc>', which does not
        match the member's name '<member_name>'. Please upload the correct document
        belonging to the member."
     Do NOT proceed to a claim decision.

Tools:
- verify_documents(items) — Call FIRST. Pass {documents, claim_category, policy_terms}.
  Returns classified docs + required_docs + optional_docs. YOU decide if requirements are met.
- extract_documents(items) — Call only if all required docs present.
- check_policy(items) — Call only if extraction succeeded.
- decide_claim(items) — Call LAST. Return its output directly as final ClaimOut.

Important — Graceful Degradation:
- If any tool call fails (returns an error), do NOT crash the pipeline.
- Log what failed and continue with whatever data you have.
- Pass the failure information downstream so the decision maker can lower confidence.
- If simulate_component_failure is true in the input, one tool may fail intentionally — handle it gracefully.

Data flow (only proceed if prior step succeeded):
1) verify_documents(documents, claim_category). Check returned transactions.
   - Required doc missing → STOP REJECTED.
   - Required doc unreadable → STOP MANUAL_REVIEW.
   - patient_name mismatch → STOP MANUAL_REVIEW.
   - Proceed only if all required docs present, valid, names match.
2) extract_documents(documents). Proceed only if success.
3) check_policy(claim, member, extracted_data, policy_terms).
4) detect_fraud(member_id, claimed_amount, extracted_data, claim_history, policy_terms).
5) decide_claim(verification, extraction, policy_result, fraud_result, claim, policy_terms). Call LAST.

policy_terms is in your input. Pass it to verify_documents, check_policy, detect_fraud, decide_claim.

If rules A, B, C all pass, you MUST call all 5 tools in sequence — do not skip.

Do NOT compute approved_amount or decision yourself. Return decide_claim's output directly.
"""


def build_agent() -> Agent:
    instr = f"{RECOMMENDED_PROMPT_PREFIX}\n{INSTRUCTIONS}"
    return Agent(
        name="HealthInsuranceClaimProcessor",
        instructions=instr,
        model=CLAIM_AGENT_MODEL,
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

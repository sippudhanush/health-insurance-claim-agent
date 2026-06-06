from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel
from agents import Agent, Runner, ModelSettings, RunConfig, trace
from agents.tracing import add_trace_processor
from agents.tracing.processors import ConsoleSpanExporter
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

from health_insurance_agent.tools.document_verifier import verify_documents
from health_insurance_agent.tools.document_extractor import extract_documents
from health_insurance_agent.tools.policy_checker import check_policy
from health_insurance_agent.tools.fraud_detector import detect_fraud
from health_insurance_agent.tools.decision_maker import decide_claim

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
        add_trace_processor(ConsoleSpanExporter())
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

Tools:
- verify_documents(items) — Verify uploaded docs against policy requirements
- extract_documents(items) — Extract structured data from document images via vision AI
- check_policy(items) — Evaluate claim against policy terms from policy_terms
- detect_fraud(items) — Analyse fraud risk using policy fraud thresholds
- decide_claim(items) — Make final decision. Call LAST.

Important — Graceful Degradation:
- If any tool call fails (returns an error), do NOT crash the pipeline.
- Log what failed and continue with whatever data you have.
- Pass the failure information downstream so the decision maker can lower confidence.
- If simulate_component_failure is true in the input, one tool may fail intentionally — handle it gracefully.

Data flow:
1) verify_documents: pass the documents + policy_terms. If overall_valid=false → STOP, return error immediately with specific messages about what's wrong.
2) extract_documents: pass documents with base64 images. Handle extraction failures gracefully.
3) check_policy: pass {claim, member, extracted_data, policy_terms} for all policy checks.
4) detect_fraud: pass {member_id, claimed_amount, extracted_data, claim_history, policy_terms}.
5) decide_claim: pass ALL outputs from steps 1-4 + original claim + policy_terms. Call LAST. Return its output.

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
        model_settings=ModelSettings(reasoning={"effort": "low"}),
        tools=[
            verify_documents,
            extract_documents,
            check_policy,
            detect_fraud,
            decide_claim,
        ],
        output_type=ClaimOut,
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

    payload: dict = {
        "claim": {
            "claim_id": claim_id,
            "member_id": claim_data.get("member_id"),
            "policy_id": claim_data.get("policy_id"),
            "claim_category": claim_data.get("claim_category"),
            "treatment_date": claim_data.get("treatment_date"),
            "claimed_amount": claim_data.get("claimed_amount"),
            "hospital_name": claim_data.get("hospital_name"),
        },
        "documents": claim_data.get("documents", []),
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
                max_turns=30,
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

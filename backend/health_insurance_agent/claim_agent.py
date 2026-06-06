from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List
from pydantic import BaseModel
from agents import Agent, Runner, ModelSettings, RunConfig, trace
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


class ClaimOut(BaseModel):
    claim_id: str
    decision: str
    approved_amount: float | None = None
    confidence_score: float
    rejection_reasons: list[str] = []
    reasoning: str = ""
    trace: dict = {}


INSTRUCTIONS = """
You are HealthInsuranceClaimProcessor. Use only the provided tools to process health insurance claims.

Tools available:
- verify_documents(items) - Verify uploaded documents match claim category requirements
- extract_documents(items) - Extract structured data from document images using vision AI
- check_policy(items) - Evaluate claim against policy terms
- detect_fraud(items) - Analyse the claim for fraud signals
- decide_claim(items) - Make the final claim decision

Important coordination rules:
- Always pass all required fields to each tool. Each tool receives a JSON string with all relevant data.
- The agent will NOT send precomputed lists or context beyond what's extracted.

Data flow (strict):
1) Document Verification
   - Call: `verify_documents(items)`
   - Input items: list of objects with keys:
     - transaction_uuid (string)
     - filename (string)
     - doc_type_hint (string)
     - claim_type (string)
     - quality (string)
   - Output: validates document types and checks required docs are present
   - If overall_valid is false, STOP - return error

2) Document Extraction
   - Call: `extract_documents(items)`
   - Input items: list of objects with keys:
     - transaction_uuid (string)
     - doc_type (string)
     - base64_content (string)
   - Output: structured data from each document (diagnosis, medicines, totals, etc.)

3) Policy Check
   - Call: `check_policy(items)`
   - Input includes: claim details, extracted data, member info, policy terms
   - Output: eligibility, approved amount estimate, individual check results

4) Fraud Detection
   - Call: `detect_fraud(items)`
   - Input includes: member_id, claimed_amount, extracted_data, claim_history
   - Output: fraud_score, signals, manual_review_required flag

5) Final Decision
   - Call: `decide_claim(items)`
   - Input: ALL outputs from steps 1-4 plus original claim
   - Output: final decision, approved_amount, confidence, reasoning
   - Call LAST - return its output as the final result

Workflow summary (order of calls):
- Start with raw claim data -> prepare minimal items and pass to verify_documents.
- If verification fails, return error immediately.
- Pass verified documents to extract_documents for vision extraction.
- Pass claim + extracted data to check_policy and detect_fraud.
- Pass everything to decide_claim for final synthesis.
- Return the final decision output.

Output format:
Return ONLY the final JSON object from decide_claim.
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

    with trace("Health Insurance Claim Processing", group_id=claim_id):
        logger.info("Processing claim: %s", claim_id)

        agent = build_agent()
        res = await Runner.run(
            agent,
            input=json.dumps(claim_data, ensure_ascii=False),
            max_turns=30,
            run_config=RunConfig(workflow_name="Health Insurance Claim Agent"),
        )

    result = getattr(res, "final_output", res)
    if isinstance(result, ClaimOut):
        output = result.model_dump()
    elif isinstance(result, dict):
        output = result
    else:
        output = {"claim_id": claim_id, "decision": "ERROR", "confidence_score": 0.0, "trace": {}}

    output.setdefault("claim_id", claim_id)
    logger.info("Claim %s processed in %.2f seconds: %s", claim_id, time.time() - start, output.get("decision"))
    return output


async def process_claim_batch(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for claim_data in claims:
        result = await process_claim(claim_data)
        results.append(result)
    return results

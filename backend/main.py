import asyncio
import json
import uuid
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from health_insurance_agent.claim_agent import process_claim

POLICY_PATH = Path(__file__).parent / "data" / "policy_terms.json"
results_store: dict = {}


def load_policy():
    with open(POLICY_PATH) as f:
        return json.load(f)


class DocumentInput(BaseModel):
    file_id: str
    file_name: str | None = None
    actual_type: str | None = None
    base64_content: str | None = None


class ClaimInput(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: str
    claimed_amount: float
    hospital_name: str | None = None
    claims_history: list[dict] | None = None
    simulate_component_failure: bool | None = None
    documents: list[DocumentInput] = []


app = FastAPI(title="Health Insurance Claim Agent")


@app.post("/api/claims")
async def submit_claim(input_data: ClaimInput):
    claim_id = f"CLM_{uuid.uuid4().hex[:8].upper()}"

    claim_data = {
        "claim_id": claim_id,
        "member_id": input_data.member_id,
        "policy_id": input_data.policy_id,
        "claim_category": input_data.claim_category,
        "treatment_date": input_data.treatment_date,
        "claimed_amount": input_data.claimed_amount,
        "hospital_name": input_data.hospital_name,
        "claims_history": input_data.claims_history or [],
        "simulate_component_failure": input_data.simulate_component_failure or False,
        "documents": [
            {
                "transaction_uuid": d.file_id,
                "filename": d.file_name or d.file_id,
                "doc_type_hint": d.actual_type or "UNKNOWN",
                "base64_content": d.base64_content or "",
                "quality": "GOOD",
            }
            for d in input_data.documents
        ],
    }

    result = await process_claim(claim_data)
    results_store[claim_id] = result
    return result


@app.get("/api/claims/{claim_id}")
async def get_claim(claim_id: str):
    result = results_store.get(claim_id)
    if not result:
        return {"error": "Claim not found"}
    return result


@app.get("/api/policy")
async def get_policy():
    return load_policy()


@app.get("/health")
async def health():
    return {"status": "healthy"}

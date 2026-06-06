from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from core.database import get_db, init_db
from core.config import settings

from schemas.claim import ClaimInput
from schemas.decision import DecisionResponse, TraceResponse

from models import Claim, FileStatus
from pipeline import run_pipeline

POLICY_PATH = Path(__file__).parent / "data" / "policy_terms.json"
_policy_terms: dict | None = None


def load_policy():
    global _policy_terms
    if _policy_terms is None:
        with open(POLICY_PATH) as f:
            _policy_terms = json.load(f)
    return _policy_terms


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    load_policy()
    yield


app = FastAPI(title="Plum Claims Processing System", version="1.0.0", lifespan=lifespan)


async def claim_stream(input_data: ClaimInput, db: AsyncSession, claim: Claim):
    try:
        policy_terms = load_policy()
        yield {"event": "start", "data": json.dumps({"claim_id": claim.id, "status": "PROCESSING"})}

        claim_data = {
            "claim_id": claim.id,
            "member_id": input_data.member_id,
            "policy_id": input_data.policy_id,
            "claim_category": input_data.claim_category,
            "treatment_date": str(input_data.treatment_date),
            "claimed_amount": input_data.claimed_amount,
            "hospital_name": input_data.hospital_name,
            "documents": [d.model_dump() for d in input_data.documents],
            "claims_history": input_data.claims_history or [],
        }

        async for event in run_pipeline(claim_data, policy_terms, settings.groq_api_key):
            if event["event"] == "result":
                data = json.loads(event["data"])
                claim.status = data.get("decision", "ERROR")
                claim.decision = data.get("decision")
                claim.approved_amount = data.get("approved_amount")
                claim.confidence_score = data.get("confidence")
                claim.rejection_reasons = [data.get("reason", "")]
                claim.trace = data.get("trace", {})
                db.add(claim)
                await db.flush()

                for d in input_data.documents:
                    db.add(FileStatus(
                        claim_id=claim.id,
                        file_uuid=d.file_id,
                        original_name=d.file_name or d.file_id,
                        actual_type=d.actual_type or "UNKNOWN",
                    ))
                await db.flush()
            elif event["event"] == "error":
                claim.status = "DOCUMENT_ERROR"
                db.add(claim)
                await db.flush()

            yield event

    except Exception as e:
        yield {"event": "error", "data": json.dumps({"message": str(e)})}
        yield {"event": "done", "data": "{}"}


@app.post("/api/claims")
async def submit_claim(input_data: ClaimInput, db: AsyncSession = Depends(get_db)):
    claim = Claim(
        member_id=input_data.member_id,
        policy_id=input_data.policy_id,
        claim_category=input_data.claim_category,
        treatment_date=input_data.treatment_date,
        claimed_amount=input_data.claimed_amount,
        hospital_name=input_data.hospital_name,
        ytd_claims_amount=input_data.ytd_claims_amount,
        claims_history=input_data.claims_history,
        simulate_component_failure=input_data.simulate_component_failure,
        status="PROCESSING",
    )
    db.add(claim)
    await db.flush()
    return EventSourceResponse(claim_stream(input_data, db, claim))


@app.get("/api/claims/{claim_id}", response_model=DecisionResponse)
async def get_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return DecisionResponse(
        claim_id=claim.id,
        decision=claim.decision or "PENDING",
        approved_amount=claim.approved_amount,
        confidence_score=claim.confidence_score or 0.0,
        rejection_reasons=claim.rejection_reasons or [],
        trace=claim.trace or {},
    )


@app.get("/api/claims/{claim_id}/trace", response_model=TraceResponse)
async def get_claim_trace(claim_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return TraceResponse(
        claim_id=claim.id,
        status=claim.status,
        decision=claim.decision,
        approved_amount=claim.approved_amount,
        confidence_score=claim.confidence_score,
        trace=claim.trace,
    )


@app.get("/api/policy")
async def get_policy():
    return load_policy()


@app.get("/health")
async def health():
    return {"status": "healthy"}

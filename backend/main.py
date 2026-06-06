from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db, init_db

from schemas.claim import ClaimInput, ClaimResponse
from schemas.decision import DecisionResponse, TraceResponse

from agents.extraction_agent import ExtractionAgent
from agents.validation_agent import ValidationAgent
from agents.policy_agent import PolicyAgent
from agents.fraud_agent import FraudAgent
from agents.decision_agent import DecisionEngineAgent

from models.claim import Claim


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Plum Claims Processing System", version="1.0.0", lifespan=lifespan)


@app.post("/api/claims", response_model=ClaimResponse)
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
        status="RECEIVED",
    )
    db.add(claim)
    await db.flush()

    # Stage 1: Light Extraction
    extraction_agent = ExtractionAgent(db)
    doc_dicts = [d.model_dump() for d in input_data.documents]
    light_results = await extraction_agent.light_extract(claim.id, doc_dicts)

    # Stage 2: Document Validation (early exit for doc problems)
    validation_agent = ValidationAgent()
    validation_result = validation_agent.validate(
        input_data.claim_category, light_results
    )

    if not validation_result.valid:
        claim.status = "DOCUMENT_ERROR"
        db.add(claim)
        await db.commit()

        if validation_result.errors:
            err = validation_result.errors[0]
            raise HTTPException(
                status_code=422,
                detail={
                    "code": err.code,
                    "message": err.message,
                    "details": err.details,
                    "claim_id": claim.id,
                },
            )

    # Stage 3: Deep Extraction
    deep_results = await extraction_agent.deep_extract(
        claim.id,
        [
            {
                "file_id": r.file_id,
                "detected_type": r.detected_type,
                "quality": r.quality,
                "actual_type": d.actual_type,
                "content": d.content,
                "file_name": d.file_name,
            }
            for r, d in zip(light_results, input_data.documents)
        ],
    )

    # Stage 4: Policy Evaluation
    policy_agent = PolicyAgent(db)
    policy_result = await policy_agent.evaluate(
        claim_id=claim.id,
        member_id=input_data.member_id,
        category=input_data.claim_category,
        claimed_amount=input_data.claimed_amount,
        treatment_date=input_data.treatment_date,
        hospital_name=input_data.hospital_name,
        extracted_docs=deep_results,
        ytd_claims_amount=input_data.ytd_claims_amount,
    )

    # Stage 5: Fraud Detection
    fraud_agent = FraudAgent(db)
    fraud_result = await fraud_agent.detect(
        claim_id=claim.id,
        member_id=input_data.member_id,
        claimed_amount=input_data.claimed_amount,
        treatment_date=input_data.treatment_date,
        claims_history=input_data.claims_history,
    )

    # Stage 6: Decision Engine
    decision_agent = DecisionEngineAgent(db)
    decision_output = await decision_agent.decide(
        claim_id=claim.id,
        validation_result=validation_result,
        extracted_docs=deep_results,
        policy_result=policy_result,
        fraud_result=fraud_result,
        extraction_agent=extraction_agent,
        claimed_amount=input_data.claimed_amount,
    )

    claim.status = decision_output.decision
    claim.decision = decision_output.decision
    claim.approved_amount = decision_output.approved_amount
    claim.confidence_score = decision_output.confidence_score
    claim.rejection_reasons = decision_output.rejection_reasons
    claim.trace = decision_output.trace
    db.add(claim)
    await db.commit()

    return ClaimResponse(claim_id=claim.id, status=claim.status)


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


@app.get("/health")
async def health():
    return {"status": "healthy"}

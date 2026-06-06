from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from core.database import get_db, init_db

from schemas.claim import ClaimInput
from schemas.decision import DecisionResponse, TraceResponse

from agents.extraction_agent import ExtractionAgent
from agents.validation_agent import ValidationAgent
from agents.policy_agent import PolicyAgent
from agents.fraud_agent import FraudAgent
from agents.decision_agent import DecisionEngineAgent

from models import Claim, FileStatus
from services.langfuse_client import langfuse


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Plum Claims Processing System", version="1.0.0", lifespan=lifespan)


async def claim_stream(input_data: ClaimInput, db: AsyncSession, claim: Claim):
    try:
        root_trace = langfuse.trace(
            id=claim.id,
            name="claim-processing",
            input={
                "member_id": input_data.member_id,
                "category": input_data.claim_category,
                "claimed_amount": input_data.claimed_amount,
            },
        ) if langfuse else None

        # Stream opened — notify client with claim_id
        yield {"event": "start", "data": json.dumps({"claim_id": claim.id, "status": "PROCESSING"})}

        # Stage 1: Light Extraction
        yield {"event": "progress", "data": json.dumps({"step": "extraction", "status": "running"})}
        extraction_agent = ExtractionAgent(db)
        doc_dicts = [d.model_dump() for d in input_data.documents]
        light_results = await extraction_agent.light_extract(claim.id, doc_dicts)
        if root_trace:
            root_trace.span(name="light_extraction", output={"document_count": len(light_results)})
        yield {"event": "progress", "data": json.dumps({"step": "extraction", "status": "done", "files": len(light_results)})}

        # Stage 2: Document Validation (early exit for doc problems)
        yield {"event": "progress", "data": json.dumps({"step": "validation", "status": "running"})}
        validation_agent = ValidationAgent()
        validation_result = validation_agent.validate(input_data.claim_category, light_results)

        if not validation_result.valid:
            claim.status = "DOCUMENT_ERROR"
            db.add(claim)
            await db.flush()
            if root_trace:
                root_trace.span(name="validation", output={"status": "FAILED", "errors": [e.code for e in validation_result.errors]})
            if langfuse:
                langfuse.flush()
            if validation_result.errors:
                err = validation_result.errors[0]
                yield {"event": "error", "data": json.dumps({"code": err.code, "message": err.message, "details": err.details, "claim_id": claim.id})}
                yield {"event": "done", "data": "{}"}
                return

        if root_trace:
            root_trace.span(name="validation", output={"status": "PASSED"})
        yield {"event": "progress", "data": json.dumps({"step": "validation", "status": "passed"})}

        # Stage 3: Deep Extraction
        yield {"event": "progress", "data": json.dumps({"step": "deep_extraction", "status": "running"})}
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
        deep_status = "degraded" if extraction_agent.degraded else "done"
        if root_trace:
            root_trace.span(name="deep_extraction", output={"document_count": len(deep_results), "degraded": extraction_agent.degraded})
        yield {"event": "progress", "data": json.dumps({"step": "deep_extraction", "status": deep_status})}

        for d in input_data.documents:
            db.add(FileStatus(
                claim_id=claim.id,
                file_uuid=d.file_id,
                original_name=d.file_name or d.file_id,
                actual_type=d.actual_type or "UNKNOWN",
            ))
        await db.flush()

        # Stage 4: Policy Evaluation
        yield {"event": "progress", "data": json.dumps({"step": "policy", "status": "running"})}
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
        if root_trace:
            root_trace.span(name="policy_evaluation", output={"eligible": policy_result.eligible})
        if policy_result.eligible:
            yield {"event": "progress", "data": json.dumps({"step": "policy", "status": "passed"})}
        else:
            yield {"event": "progress", "data": json.dumps({"step": "policy", "status": "rejected", "reasons": policy_result.rejection_reasons})}

        # Stage 5: Fraud Detection
        yield {"event": "progress", "data": json.dumps({"step": "fraud", "status": "running"})}
        fraud_agent = FraudAgent(db)
        fraud_result = await fraud_agent.detect(
            claim_id=claim.id,
            member_id=input_data.member_id,
            claimed_amount=input_data.claimed_amount,
            treatment_date=input_data.treatment_date,
            claims_history=input_data.claims_history,
        )
        if root_trace:
            root_trace.span(name="fraud_detection", output={"fraud_score": fraud_result.fraud_score})
        if fraud_result.fraud_score >= 0.8:
            yield {"event": "progress", "data": json.dumps({"step": "fraud", "status": "flagged", "score": fraud_result.fraud_score})}
        else:
            yield {"event": "progress", "data": json.dumps({"step": "fraud", "status": "passed", "score": fraud_result.fraud_score})}

        # Stage 6: Decision Engine
        yield {"event": "progress", "data": json.dumps({"step": "decision", "status": "running"})}
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
        await db.flush()

        if root_trace:
            root_trace.span(name="decision", output={"decision": decision_output.decision, "approved_amount": decision_output.approved_amount})
            root_trace.update(output={"status": decision_output.decision, "claim_id": claim.id})
        if langfuse:
            langfuse.flush()

        yield {"event": "result", "data": decision_output.model_dump_json()}
        yield {"event": "done", "data": "{}"}

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
    path = Path(__file__).parent / "data" / "policy_terms.json"
    with open(path) as f:
        policy = json.load(f)
    return policy


@app.get("/health")
async def health():
    return {"status": "healthy"}

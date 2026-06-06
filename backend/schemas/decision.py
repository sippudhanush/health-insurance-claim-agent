from pydantic import BaseModel


class PolicyCheckResult(BaseModel):
    check_name: str
    status: str
    details: dict | None = None


class PolicyResult(BaseModel):
    eligible: bool
    approved_amount_estimate: float | None = None
    checks: list[PolicyCheckResult] = []
    network_discount_percent: float = 0.0
    copay_percent: float = 0.0
    rejection_reasons: list[str] = []


class FraudResult(BaseModel):
    fraud_score: float = 0.0
    signals: list[str] = []


class LineItemBreakdown(BaseModel):
    description: str
    amount: float
    approved: bool
    reason: str | None = None


class DecisionOutput(BaseModel):
    claim_id: str
    decision: str
    approved_amount: float | None = None
    confidence_score: float
    rejection_reasons: list[str] = []
    line_item_breakdown: list[LineItemBreakdown] | None = None
    trace: dict
    degradation_notes: list[str] = []


class DecisionResponse(BaseModel):
    claim_id: str
    decision: str
    approved_amount: float | None = None
    confidence_score: float
    rejection_reasons: list[str] = []
    line_item_breakdown: list[dict] | None = None
    trace: dict
    degradation_notes: list[str] = []


class TraceResponse(BaseModel):
    claim_id: str
    status: str
    decision: str | None = None
    approved_amount: float | None = None
    confidence_score: float | None = None
    trace: dict | None = None

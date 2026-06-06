from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Date

from models import Claim, FraudCheck
from schemas.decision import FraudResult


class FraudAgent:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def detect(
        self,
        claim_id: str,
        member_id: str,
        claimed_amount: float,
        treatment_date: date,
        claims_history: list[dict] | None = None,
    ) -> FraudResult:
        signals: list[str] = []
        fraud_score = 0.0

        if claims_history:
            same_day_count = sum(
                1 for c in claims_history if c.get("date") == treatment_date.isoformat()
            )
        else:
            result = await self.db.execute(
                select(func.count(Claim.id)).where(
                    Claim.member_id == member_id,
                    func.cast(Claim.created_at, Date) == treatment_date,
                    Claim.id != claim_id,
                )
            )
            same_day_count = result.scalar() or 0

        if same_day_count >= 2:
            signals.append(
                f"SAME_DAY_CLAIMS_EXCEEDED: {same_day_count + 1} claims on {treatment_date}"
            )
            fraud_score += 0.5

        if claims_history:
            monthly_count = sum(
                1
                for c in claims_history
                if c.get("date", "")[:7] == treatment_date.isoformat()[:7]
            )
        else:
            result = await self.db.execute(
                select(func.count(Claim.id)).where(
                    Claim.member_id == member_id,
                    func.extract("year", Claim.created_at) == treatment_date.year,
                    func.extract("month", Claim.created_at) == treatment_date.month,
                    Claim.id != claim_id,
                )
            )
            monthly_count = result.scalar() or 0

        monthly_limit = 6  # from fraud_thresholds
        if monthly_count >= monthly_limit:
            signals.append(
                f"HIGH_MONTHLY_VOLUME: {monthly_count + 1} claims this month"
            )
            fraud_score += 0.3

        high_value_threshold = 25000  # from fraud_thresholds
        if claimed_amount >= high_value_threshold:
            signals.append(f"HIGH_VALUE_CLAIM: ₹{claimed_amount}")
            fraud_score += 0.2

        fraud_score = min(fraud_score, 1.0)

        self.db.add(
            FraudCheck(
                claim_id=claim_id,
                fraud_score=fraud_score,
                signals=signals,
            )
        )
        await self.db.flush()

        return FraudResult(fraud_score=fraud_score, signals=signals)

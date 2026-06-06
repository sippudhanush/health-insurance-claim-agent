import json
from datetime import date, datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from models import PolicyCheck
from schemas.decision import PolicyResult, PolicyCheckResult
from core.enums import RejectionReason


POLICY_PATH = Path(__file__).parent.parent / "data" / "policy_terms.json"


class PolicyAgent:
    def __init__(self, db: AsyncSession):
        self.db = db
        with open(POLICY_PATH) as f:
            self.policy = json.load(f)

    async def evaluate(
        self,
        claim_id: str,
        member_id: str,
        category: str,
        claimed_amount: float,
        treatment_date: date,
        hospital_name: str | None = None,
        extracted_docs: list[dict] | None = None,
        ytd_claims_amount: float | None = None,
    ) -> PolicyResult:
        checks: list[PolicyCheckResult] = []
        rejection_reasons: list[str] = []
        member = self._find_member(member_id)
        category_config = self.policy["opd_categories"].get(category.lower())

        if not category_config or not category_config.get("covered", False):
            checks.append(
                PolicyCheckResult(
                    check_name="coverage",
                    status="FAILED",
                    details={"category": category, "covered": False},
                )
            )
            rejection_reasons.append(RejectionReason.UNCOVERED_CATEGORY.value)
            return PolicyResult(
                eligible=False,
                checks=checks,
                approved_amount_estimate=0,
                rejection_reasons=rejection_reasons,
            )

        checks.append(
            PolicyCheckResult(
                check_name="coverage",
                status="PASSED",
                details={"category": category, "covered": True},
            )
        )
        sub_limit = category_config.get("sub_limit")
        copay = category_config.get("copay_percent", 0)
        network_discount = category_config.get("network_discount_percent", 0)

        # Waiting periods
        wp_check = self._check_waiting_periods(member, treatment_date, extracted_docs)
        checks.append(wp_check)
        if wp_check.status == "FAILED":
            rejection_reasons.append(RejectionReason.WAITING_PERIOD.value)

        # Exclusions
        excl_check = self._check_exclusions(category, extracted_docs)
        checks.append(excl_check)
        if excl_check.status == "FAILED":
            rejection_reasons.append(RejectionReason.EXCLUDED_CONDITION.value)

        # Pre-auth
        preauth_check = self._check_pre_auth(category, claimed_amount, extracted_docs)
        checks.append(preauth_check)
        if preauth_check.status == "FAILED":
            rejection_reasons.append(RejectionReason.PRE_AUTH_MISSING.value)

        # Per-claim limit
        per_claim_limit = self.policy["coverage"]["per_claim_limit"]
        if claimed_amount > per_claim_limit:
            checks.append(
                PolicyCheckResult(
                    check_name="per_claim_limit",
                    status="FAILED",
                    details={"limit": per_claim_limit, "claimed": claimed_amount},
                )
            )
            rejection_reasons.append(RejectionReason.PER_CLAIM_EXCEEDED.value)
        else:
            checks.append(
                PolicyCheckResult(
                    check_name="per_claim_limit",
                    status="PASSED",
                    details={"limit": per_claim_limit},
                )
            )

        # Sub-limit (soft cap - reduces approved amount but doesn't reject)
        if sub_limit and claimed_amount > sub_limit:
            checks.append(
                PolicyCheckResult(
                    check_name="sub_limit",
                    status="WARNING",
                    details={
                        "sub_limit": sub_limit,
                        "claimed": claimed_amount,
                        "action": "Capping at sub_limit",
                    },
                )
            )
        else:
            checks.append(
                PolicyCheckResult(
                    check_name="sub_limit",
                    status="PASSED" if not sub_limit else "PASSED",
                    details={"sub_limit": sub_limit},
                )
            )

        eligible = len(rejection_reasons) == 0

        # Calculate approved amount
        approved = claimed_amount if eligible else 0.0
        breakdown_details = {"original": claimed_amount}

        if eligible:
            if hospital_name and self._is_network_hospital(hospital_name):
                discount = round(claimed_amount * network_discount / 100, 2)
                after_discount = round(claimed_amount - discount, 2)
                breakdown_details["network_discount"] = f"{network_discount}%"
                breakdown_details["after_discount"] = after_discount
                copay_amount = round(after_discount * copay / 100, 2)
                approved = round(after_discount - copay_amount, 2)
                breakdown_details["copay"] = f"{copay}%"
                breakdown_details["copay_amount"] = copay_amount
                breakdown_details["approved_amount"] = approved
            else:
                copay_amount = round(claimed_amount * copay / 100, 2)
                approved = round(claimed_amount - copay_amount, 2)
                breakdown_details["copay"] = f"{copay}%"
                breakdown_details["copay_amount"] = copay_amount
                breakdown_details["approved_amount"] = approved

        for check in checks:
            self.db.add(
                PolicyCheck(
                    claim_id=claim_id,
                    check_name=check.check_name,
                    status=check.status,
                    details=check.details,
                )
            )
        await self.db.flush()

        return PolicyResult(
            eligible=eligible,
            approved_amount_estimate=approved,
            checks=checks,
            network_discount_percent=network_discount,
            copay_percent=copay,
            rejection_reasons=rejection_reasons,
        )

    def _find_member(self, member_id: str) -> dict | None:
        for m in self.policy["members"]:
            if m["member_id"] == member_id:
                return m
        return None

    def _check_waiting_periods(
        self,
        member: dict | None,
        treatment_date: date,
        extracted_docs: list[dict] | None,
    ) -> PolicyCheckResult:
        if not member:
            return PolicyCheckResult(
                check_name="waiting_period",
                status="FAILED",
                details={"reason": "Member not found"},
            )
        join_date = datetime.strptime(member["join_date"], "%Y-%m-%d").date()
        days_since_join = (treatment_date - join_date).days
        initial_wp = self.policy["waiting_periods"]["initial_waiting_period_days"]

        if days_since_join < initial_wp:
            eligible_date = join_date.isoformat()
            return PolicyCheckResult(
                check_name="waiting_period",
                status="FAILED",
                details={
                    "reason": "Initial waiting period",
                    "eligible_from": eligible_date,
                    "days_remaining": initial_wp - days_since_join,
                },
            )

        if extracted_docs:
            diagnosis = self._get_diagnosis_from_docs(extracted_docs)
            specific_conditions = self.policy["waiting_periods"].get(
                "specific_conditions", {}
            )
            condition_key = self._match_condition(diagnosis, specific_conditions)
            if condition_key:
                wp_days = specific_conditions[condition_key]
                if days_since_join < wp_days:
                    eligible_date = join_date.isoformat()
                    return PolicyCheckResult(
                        check_name="waiting_period",
                        status="FAILED",
                        details={
                            "reason": f"Waiting period for {condition_key}",
                            "condition": condition_key,
                            "eligible_from": eligible_date,
                            "days_remaining": wp_days - days_since_join,
                        },
                    )

        return PolicyCheckResult(
            check_name="waiting_period",
            status="PASSED",
            details={"days_since_join": days_since_join},
        )

    EXCLUSION_KEYWORDS = {
        "obesity": "Obesity and weight loss programs",
        "bariatric": "Bariatric surgery",
        "cosmetic": "Cosmetic or aesthetic procedures",
        "self-inflicted": "Self-inflicted injuries",
        "infertility": "Infertility and assisted reproduction",
        "experimental": "Experimental treatments",
    }

    def _check_exclusions(
        self, category: str, extracted_docs: list[dict] | None
    ) -> PolicyCheckResult:
        if not extracted_docs:
            return PolicyCheckResult(
                check_name="exclusions", status="PASSED", details={}
            )

        diagnosis = self._get_diagnosis_from_docs(extracted_docs)
        treatment = self._get_treatment_from_docs(extracted_docs)
        conditions = self.policy["exclusions"].get("conditions", [])
        all_text = (diagnosis + " " + treatment).lower()

        for cond in conditions:
            cond_lower = cond.lower()
            if cond_lower in all_text:
                return PolicyCheckResult(
                    check_name="exclusions",
                    status="FAILED",
                    details={"matched": cond, "condition": cond},
                )

        for keyword, condition_name in self.EXCLUSION_KEYWORDS.items():
            if keyword in all_text:
                return PolicyCheckResult(
                    check_name="exclusions",
                    status="FAILED",
                    details={"matched": condition_name, "keyword": keyword},
                )

        return PolicyCheckResult(check_name="exclusions", status="PASSED", details={})

    def _check_pre_auth(
        self, category: str, claimed_amount: float, extracted_docs: list[dict] | None
    ) -> PolicyCheckResult:
        if not extracted_docs:
            return PolicyCheckResult(check_name="pre_auth", status="PASSED", details={})
        treatment = self._get_treatment_from_docs(extracted_docs).lower()
        tests_ordered = self._get_tests_from_docs(extracted_docs)
        all_content = (treatment + " " + " ".join(tests_ordered)).lower()
        pre_auth_config = self.policy.get("pre_authorization", {})
        required_items = pre_auth_config.get("required_for", [])

        for item in required_items:
            item_lower = item.lower()
            if "mri" in item_lower and ("mri" in all_content):
                thresholds = (
                    self.policy["opd_categories"]
                    .get("diagnostic", {})
                    .get("high_value_tests_requiring_pre_auth", [])
                )
                for test in thresholds:
                    if test.lower() in all_content and claimed_amount > 10000:
                        return PolicyCheckResult(
                            check_name="pre_auth",
                            status="FAILED",
                            details={
                                "required_for": item,
                                "claimed_amount": claimed_amount,
                                "threshold": 10000,
                                "action": "Please obtain pre-authorization before resubmitting.",
                            },
                        )
                if claimed_amount > 10000:
                    return PolicyCheckResult(
                        check_name="pre_auth",
                        status="FAILED",
                        details={
                            "required_for": item,
                            "claimed_amount": claimed_amount,
                            "threshold": 10000,
                            "action": "Please obtain pre-authorization before resubmitting.",
                        },
                    )
            elif item_lower in all_content:
                return PolicyCheckResult(
                    check_name="pre_auth",
                    status="FAILED",
                    details={"required_for": item},
                )
        return PolicyCheckResult(check_name="pre_auth", status="PASSED", details={})

    def _is_network_hospital(self, hospital_name: str) -> bool:
        network = self.policy.get("network_hospitals", [])
        return any(
            h.lower() in hospital_name.lower() or hospital_name.lower() in h.lower()
            for h in network
        )

    def _get_diagnosis_from_docs(self, docs: list[dict]) -> str:
        for doc in docs:
            content = doc.get("extracted_content") or doc.get("content") or {}
            if isinstance(content, dict):
                diag = content.get("diagnosis", "")
                if diag:
                    return diag
        return ""

    def _get_treatment_from_docs(self, docs: list[dict]) -> str:
        for doc in docs:
            content = doc.get("extracted_content") or doc.get("content") or {}
            if isinstance(content, dict):
                treatment = content.get("treatment", "")
                if treatment:
                    return treatment
                items = content.get("line_items", []) or content.get("medicines", [])
                if items:
                    return " ".join(
                        i.get("description", str(i))
                        for i in items
                        if isinstance(i, dict)
                    )
        return ""

    def _get_tests_from_docs(self, docs: list[dict]) -> list[str]:
        for doc in docs:
            content = doc.get("extracted_content") or doc.get("content") or {}
            if isinstance(content, dict):
                tests = content.get("tests_ordered", []) or content.get("test_name", "")
                if isinstance(tests, str):
                    return [tests]
                return tests if isinstance(tests, list) else []
        return []

    def _match_condition(self, diagnosis: str, conditions: dict) -> str | None:
        diag_lower = diagnosis.lower()
        for condition, days in conditions.items():
            if condition.lower() in diag_lower:
                return condition
        return None

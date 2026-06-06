import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from services.llm_client import groq_client
from tools.extraction_tools import ExtractDocumentsTool, DeepExtractDocumentsTool
from tools.validation_tool import ValidateDocumentsTool
from tools.policy_tool import EvaluatePolicyTool
from tools.fraud_tool import DetectFraudTool
from tools.decision_tool import DecideClaimTool

logger = logging.getLogger("plum.orchestrator")

POLICY_PATH = Path(__file__).parent.parent / "data" / "policy_terms.json"

ORCHESTRATOR_SYSTEM_PROMPT = """You are a health insurance claims processing orchestrator. Your job is to process a claim submission by calling tools in the correct order.

AVAILABLE TOOLS:

1. extract_documents
   - What it does: Parses uploaded files and detects document type, quality, patient name
   - When to call: FIRST step, always
   - Returns: List of extracted document info with detected types and confidence

2. validate_documents
   - What it does: Validates documents against claim category requirements
   - When to call: After extract_documents
   - Returns: {valid: bool, errors: [...]}
   - IMPORTANT: If valid=false with errors, STOP. Do NOT call any more tools. Return the errors to the user.

3. deep_extract_documents
   - What it does: Extracts detailed structured data (diagnosis, medicines, line items, etc.)
   - When to call: Only if validation passed (valid=true)
   - Returns: Documents with extracted_content containing structured fields

4. evaluate_policy
   - What it does: Checks coverage, waiting periods, exclusions, pre-auth, limits, calculates approved amount
   - When to call: After deep extraction, can be same time as detect_fraud
   - Returns: {eligible, approved_amount_estimate, checks, rejection_reasons}

5. detect_fraud
   - What it does: Checks fraud signals (same-day claims, high volume, high value)
   - When to call: After deep extraction, can be same time as evaluate_policy
   - Returns: {fraud_score, signals, flagged}

6. decide_claim
   - What it does: Makes final decision (APPROVED/PARTIAL/REJECTED/MANUAL_REVIEW)
   - When to call: LAST step, after all other tools have returned
   - Returns: Final decision with trace, confidence, breakdown

WORKFLOW RULES:
1. Start with extract_documents
2. Then validate_documents — if errors, STOP and report them
3. If valid, call deep_extract_documents
4. Then call evaluate_policy AND detect_fraud (in any order)
5. Finally call decide_claim with ALL accumulated results
6. Output the final result from decide_claim as JSON

CRITICAL: Never call decide_claim without having called the prerequisite tools first."""


class OrchestratorAgent:
    def __init__(self, db: AsyncSession, claim_id: str, input_data):
        self.db = db
        self.claim_id = claim_id
        self.input_data = input_data
        self.degraded = False
        self._state: dict = {}
        self._tools: dict[str, object] = {}
        self._step_count = 0
        self._trace_updates = []
        self._policy_terms = self._load_policy_terms()

    def _load_policy_terms(self) -> dict | None:
        path = POLICY_PATH
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def _init_tools(self):
        extract = ExtractDocumentsTool(self.db)
        deep_extract = DeepExtractDocumentsTool(self.db)
        validate = ValidateDocumentsTool(self.db, policy_terms=self._policy_terms)
        policy = EvaluatePolicyTool(self.db, policy_terms=self._policy_terms)
        fraud = DetectFraudTool(self.db, policy_terms=self._policy_terms)
        decision = DecideClaimTool(self.db)

        self._tools = {
            "extract_documents": extract,
            "deep_extract_documents": deep_extract,
            "validate_documents": validate,
            "evaluate_policy": policy,
            "detect_fraud": fraud,
            "decide_claim": decision,
        }

    def _get_tool_defs(self) -> list[dict]:
        return [t.to_openai_tool() for t in self._tools.values()]

    async def _execute_tool(self, tool_name: str, args: dict) -> dict:
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")
        logger.info("Orchestrator executing tool: %s with args=%s", tool_name, list(args.keys()))
        result = await tool.run(**args)

        if isinstance(result, dict) and result.get("degraded"):
            self.degraded = True

        if isinstance(result, dict) and "documents" in result:
            self._state["extracted_docs"] = result["documents"]
        if isinstance(result, dict) and "valid" in result:
            self._state["validation"] = result
        if isinstance(result, dict) and result.get("eligible") is not None:
            self._state["policy"] = result
        if isinstance(result, dict) and "fraud_score" in result:
            self._state["fraud"] = result
        if isinstance(result, dict) and "decision" in result:
            self._state["decision"] = result

        return result

    def _build_user_message(self) -> str:
        d = self.input_data
        docs_info = "\n".join(
            f"  - {doc.file_id} ({doc.file_name or 'unnamed'}): type={doc.actual_type or 'unknown'}"
            for doc in d.documents
        )
        return f"""Process this claim:

Claim ID: {self.claim_id}
Member ID: {d.member_id}
Policy ID: {d.policy_id}
Category: {d.claim_category}
Treatment Date: {d.treatment_date}
Claimed Amount: ₹{d.claimed_amount}
Hospital: {d.hospital_name or 'Not specified'}
YTD Claims: {d.ytd_claims_amount or 0}

Uploaded Documents:
{docs_info}

Please start by calling extract_documents to process the uploaded files."""

    async def _emit_progress(self, step: str, status: str, extras: dict | None = None):
        data = {"step": step, "status": status}
        if extras:
            data.update(extras)
        self._trace_updates.append(data)

    async def process(self):
        self._init_tools()

        yield {"event": "start", "data": json.dumps({"claim_id": self.claim_id, "status": "PROCESSING"})}

        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message()},
        ]

        tool_defs = self._get_tool_defs()
        max_iterations = 15
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self._step_count += 1

            try:
                response = await groq_client.chat(messages, tools=tool_defs, max_tokens=4000)
            except Exception as e:
                logger.error("Orchestrator LLM call failed: %s", e)
                yield {"event": "error", "data": json.dumps({"message": f"Orchestrator error: {str(e)}", "claim_id": self.claim_id})}
                yield {"event": "done", "data": "{}"}
                return

            assistant_msg = {"role": "assistant", "content": response.get("content", "")}
            messages.append(assistant_msg)

            tool_calls = response.get("tool_calls")
            if not tool_calls:
                content = response.get("content", "")
                if content:
                    try:
                        result = json.loads(content)
                        if "decision" in result:
                            yield {"event": "result", "data": json.dumps(result)}
                            yield {"event": "done", "data": "{}"}
                            return
                    except json.JSONDecodeError:
                        pass
                if self._state.get("decision"):
                    result = self._state["decision"]
                    yield {"event": "result", "data": json.dumps(result)}
                    yield {"event": "done", "data": "{}"}
                    return
                yield {"event": "result", "data": json.dumps({"claim_id": self.claim_id, "decision": "ERROR", "message": "No tool calls or final output from LLM"})}
                yield {"event": "done", "data": "{}"}
                return

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                step_map = {
                    "extract_documents": "extraction",
                    "validate_documents": "validation",
                    "deep_extract_documents": "deep_extraction",
                    "evaluate_policy": "policy",
                    "detect_fraud": "fraud",
                    "decide_claim": "decision",
                }
                step_name = step_map.get(tool_name, tool_name)

                await self._emit_progress(step_name, "running")
                yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "running"})}

                try:
                    result = await self._execute_tool(tool_name, args)

                    if tool_name == "extract_documents":
                        yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "done", "files": result.get("count", 0)})}
                    elif tool_name == "validate_documents":
                        if not result.get("valid", True):
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "failed", "errors": result.get("errors", [])})}
                            yield {"event": "error", "data": json.dumps({
                                "claim_id": self.claim_id,
                                "code": result["errors"][0]["code"] if result.get("errors") else "VALIDATION_ERROR",
                                "message": result["errors"][0]["message"] if result.get("errors") else "Document validation failed",
                                "details": result,
                            })}
                            yield {"event": "done", "data": "{}"}
                            return
                        else:
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "passed"})}
                    elif tool_name == "deep_extract_documents":
                        d_status = "degraded" if result.get("degraded") else "done"
                        yield {"event": "progress", "data": json.dumps({"step": step_name, "status": d_status})}
                    elif tool_name == "evaluate_policy":
                        if result.get("eligible"):
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "passed"})}
                        else:
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "rejected", "reasons": result.get("rejection_reasons", [])})}
                    elif tool_name == "detect_fraud":
                        if result.get("flagged"):
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "flagged", "score": result.get("fraud_score")})}
                        else:
                            yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "passed", "score": result.get("fraud_score")})}
                    elif tool_name == "decide_claim":
                        yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "running"})}
                        yield {"event": "result", "data": json.dumps(result)}
                        yield {"event": "done", "data": "{}"}
                        return
                    else:
                        yield {"event": "progress", "data": json.dumps({"step": step_name, "status": "done"})}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result),
                    })

                except Exception as e:
                    logger.error("Tool %s failed: %s", tool_name, e)
                    yield {"event": "error", "data": json.dumps({"message": f"{tool_name} failed: {str(e)}", "claim_id": self.claim_id})}
                    yield {"event": "done", "data": "{}"}
                    return

        yield {"event": "error", "data": json.dumps({"message": "Orchestrator reached max iterations", "claim_id": self.claim_id})}
        yield {"event": "done", "data": "{}"}


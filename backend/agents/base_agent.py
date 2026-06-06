import json
import asyncio
import logging

from openai import AsyncOpenAI

logger = logging.getLogger("plum.agent")


class BaseAgent:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str,
        tools: list[dict] | None = None,
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools or []
        self._tool_map: dict[str, callable] = {}

    def register_tool(self, name: str, handler: callable):
        self._tool_map[name] = handler

    async def _execute_tool(self, name: str, args: dict) -> str:
        handler = self._tool_map.get(name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            result = await handler(**args) if asyncio.iscoroutinefunction(handler) else handler(**args)
            return json.dumps(result)
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e)
            return json.dumps({"error": str(e)})

    async def run(self, messages: list[dict]) -> dict:
        try:
            return await self._run(messages)
        except Exception as e:
            logger.error("Agent %s failed: %s", self.model, e)
            return {"status": "DEGRADED", "error": str(e)}

    async def _run(self, messages: list[dict]) -> dict:
        max_iterations = 10
        for _ in range(max_iterations):
            full_messages = [{"role": "system", "content": self.system_prompt}] + messages
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    tools=self.tools if self.tools else None,
                    temperature=0.1,
                )
            except Exception as e:
                if "timeout" in str(e).lower():
                    logger.warning("Groq timeout, retrying after 2s...")
                    await asyncio.sleep(2)
                    resp = await self.client.chat.completions.create(
                        model=self.model,
                        messages=full_messages,
                        tools=self.tools if self.tools else None,
                        temperature=0.1,
                    )
                else:
                    raise

            msg = resp.choices[0].message

            if msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or ""})
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result_str = await self._execute_tool(tc.function.name, args)
                    result = json.loads(result_str)
                    if tc.function.name == "verify_documents" and not result.get("valid", True):
                        return {"status": "STOPPED", "error": result.get("error_message", "Verification failed")}

                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

            else:
                content = msg.content or ""
                content = content.strip()
                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:-1])
                return json.loads(content)

        return {"status": "DEGRADED", "error": "Max iterations reached"}

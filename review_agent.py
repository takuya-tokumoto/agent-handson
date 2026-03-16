"""
レビューエージェント（A2A サーバ）。
Claude（claude-agent-sdk）でドラフトをレビューし、観点に基づいたフィードバックを返す自律型エージェント。
"""
import os
import uvicorn
from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.client import create_text_message_object
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Role

from prompts import (
    REVIEW_AGENT_DESCRIPTION,
    REVIEW_AGENT_INSTRUCTION,
    REVIEW_AGENT_NAME,
    REVIEW_AGENT_VERSION,
    REVIEW_SKILL_DESCRIPTION,
    REVIEW_SKILL_EXAMPLES,
    REVIEW_SKILL_ID,
    REVIEW_SKILL_NAME,
)

load_dotenv()

REVIEW_AGENT_HOST = "0.0.0.0"
REVIEW_AGENT_PORT = 9999


async def llm_review(draft_text: str) -> str:
    """
    Claude（claude-agent-sdk）でドラフトをレビューする。
    MCP は使わず、1 回の query でレビュー文を取得する。
    """
    prompt = f"""{REVIEW_AGENT_INSTRUCTION}

【レビュー対象ドラフト】
---
{draft_text}
---

上記のドラフトをレビューし、観点に沿ったフィードバックを出力してください。
"""

    options = ClaudeAgentOptions(
        mcp_servers={},
        allowed_tools=[],
    )

    result_text = ""
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
            if text_parts:
                result_text = "\n".join(text_parts)
        elif isinstance(msg, ResultMessage):
            if msg.result:
                result_text = msg.result
    return result_text.strip()


class ReviewExecutor(AgentExecutor):
    """A2A リクエストを受け取り、ドラフトを LLM でレビューして結果を返す実行器。"""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()
        if not (user_text and user_text.strip()):
            raise ValueError("レビュー対象のドラフトテキストが空です。入力が取得できませんでした。")
        review_content = await llm_review(user_text)
        review_msg = create_text_message_object(role=Role.agent, content=review_content)
        await event_queue.enqueue_event(review_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")


def build_agent_card(base_url: str) -> AgentCard:
    """A2A のエージェントカード（/.well-known/agent-card.json 用）を組み立てる。"""
    skill = AgentSkill(
        id=REVIEW_SKILL_ID,
        name=REVIEW_SKILL_NAME,
        description=REVIEW_SKILL_DESCRIPTION,
        tags=["review", "checklist", "confluence"],
        examples=REVIEW_SKILL_EXAMPLES,
    )
    return AgentCard(
        name=REVIEW_AGENT_NAME,
        description=REVIEW_AGENT_DESCRIPTION,
        url=base_url,
        version=REVIEW_AGENT_VERSION,
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )


def _cli() -> None:
    """エントリポイント。A2A サーバを Uvicorn で起動する。"""
    host = REVIEW_AGENT_HOST
    port = REVIEW_AGENT_PORT
    base_url = os.environ.get("A2A_CARD_URL", f"http://localhost:{port}/")

    agent_card = build_agent_card(base_url)
    request_handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    uvicorn.run(server.build(), host=host, port=port)


if __name__ == "__main__":
    _cli()

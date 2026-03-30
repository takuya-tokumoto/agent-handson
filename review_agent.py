"""
レビューエージェント（A2A サーバ）。

- 記事作成エージェントから A2A（HTTP）で「ドラフト本文」を受け取る。
- Claude で観点に基づいてレビューし、フィードバック文を返す。
- 起動すると /.well-known/agent-card.json を公開し、記事作成側の request_review ツールがここに送信する。
"""
import logging
import os
from pathlib import Path
from typing import Any

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
from logging_config import LOG_DIR, get_log_timestamp, setup_review_agent_log

load_dotenv()

# ログ出力に使うロガー名（log/review_agent_*.log に出力される）
LOGGER_NAME_REVIEW = "review_agent"

# -----------------------------------------------------------------------------
# サーバ設定（起動時のホスト・ポート）
# -----------------------------------------------------------------------------

REVIEW_AGENT_HOST = "0.0.0.0"
REVIEW_AGENT_PORT = 9999


# -----------------------------------------------------------------------------
# レビュー処理（LLM 呼び出し）
# -----------------------------------------------------------------------------


def _extract_text_from_content(content: Any) -> str:
    """メッセージの content（str または TextBlock のリスト）からテキストを抽出する。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.text for b in content if isinstance(b, TextBlock)]
        return "\n".join(parts) if parts else ""
    return str(content)


def _process_review_stream_message(msg: Any, result_text: str, logger: logging.Logger) -> str:
    """
    query() が返すストリームメッセージを 1 件処理し、更新後の result_text を返す。
    Assistant / Result はログと画面の両方に出す。その他メッセージはログにのみ内容を残す。
    """
    if isinstance(msg, AssistantMessage):
        text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        if text_parts:
            result_text = "\n".join(text_parts)
            logger.info("AssistantMessage: text_len=%s\ncontent=%s", len(result_text), result_text)
            print("[レビューエージェント Assistant]\n" + result_text)
    elif isinstance(msg, ResultMessage):
        if msg.result:
            result_text = msg.result
            logger.info("ResultMessage: result_len=%s\ncontent=%s", len(result_text), result_text)
            print("[レビューエージェント Result]\n" + result_text)
    else:
        # UserMessage / SystemMessage など、その他メッセージはログにのみ内容を残す（画面には出さない）
        content = getattr(msg, "content", None)
        text = _extract_text_from_content(content) if content is not None else ""
        kind = type(msg).__name__
        if text:
            logger.info("%s: text_len=%s\ncontent=%s", kind, len(text), text)
        else:
            logger.info("message: type=%s", kind)
    return result_text


async def llm_review(draft_text: str) -> str:
    """
    ドラフトを Claude に送り、レビュー観点に沿ったフィードバック文を 1 回の query で取得する。
    MCP は使わない（ツールなし）ため、プロンプトは文字列のまま渡してよい。
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

    logger = logging.getLogger(LOGGER_NAME_REVIEW)
    result_text = ""
    async for msg in query(prompt=prompt, options=options):
        result_text = _process_review_stream_message(msg, result_text, logger)
    out = result_text.strip()
    if not out:
        raise ValueError("レビューエージェントから空のフィードバックが返りました。ドラフト内容や API を確認してください。")
    return out


# -----------------------------------------------------------------------------
# A2A 実行器（リクエスト受付 → LLM レビュー → 返答）
# -----------------------------------------------------------------------------


class ReviewExecutor(AgentExecutor):
    """
    A2A のリクエストを受けたときに実行される処理。
    リクエスト本文をドラフトとして llm_review() に渡し、返ってきたレビュー文を A2A レスポンスで返す。
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger = logging.getLogger(LOGGER_NAME_REVIEW)
        user_text = context.get_user_input()
        if not (user_text and user_text.strip()):
            raise ValueError("レビュー対象のドラフトテキストが空です。入力が取得できませんでした。")
        logger.info("review request received content_len=%s", len(user_text))
        try:
            logger.info("llm_review start")
            review_content = await llm_review(user_text)
            logger.info("llm_review completed result_len=%s", len(review_content))
        except Exception:
            logger.exception("llm_review failed")
            raise
        review_msg = create_text_message_object(role=Role.agent, content=review_content)
        await event_queue.enqueue_event(review_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """A2A の cancel には未対応。AgentExecutor のインターフェース上必要なため NotImplementedError を返す。"""
        raise NotImplementedError("cancel not supported")


# -----------------------------------------------------------------------------
# エージェントカード（/.well-known/agent-card.json 用）
# -----------------------------------------------------------------------------


def build_agent_card(base_url: str) -> AgentCard:
    """
    A2A で公開するエージェントカードを組み立てる。
    記事作成側はこのカードの URL に SendMessage でドラフトを送る。
    """
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


# -----------------------------------------------------------------------------
# エントリポイント
# -----------------------------------------------------------------------------


def _cli() -> None:
    """ログを設定し、A2A サーバを Uvicorn で 0.0.0.0:9999 にバインドして起動する。"""
    # 記事作成エージェントと同様、同一秒で複数起動してもログが上書きされないようマイクロ秒を含める（共通形式）
    run_id = f"review_agent_{get_log_timestamp()}"
    setup_review_agent_log(run_id)
    log_path = Path(LOG_DIR) / f"{run_id}.log"
    print(f"詳細ログ: {log_path}\n")

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

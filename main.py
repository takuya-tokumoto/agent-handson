"""
記事作成エージェント（メインエントリポイント）。

- 指定 URL の Web 記事を Playwright MCP で取得し、社内向け Markdown 記事を作成する。
- レビューエージェント（A2A）を request_review ツールで呼び出し、フィードバックを反映してから最終版を出す。
- 出力は output/final_YYYYMMDD_HHMMSS.fff.md（タイムスタンプにミリ秒を含む）に保存する。

事前に review_agent.py を別プロセスで起動しておく必要があります。
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions, tool, create_sdk_mcp_server
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
from tools_action_manager import save_markdown, a2a_review
from prompts import (
    REQUEST_REVIEW_TOOL_DESCRIPTION,
    build_article_agent_prompt,
    validate_prompt_inputs,
)
from logging_config import LOG_DIR, get_log_timestamp, setup_article_agent_log

load_dotenv()

# バンドル CLI のストリームが一定時間で閉じる。この時間は「セッション開始からの経過」の可能性があり、
# 記事作成フロー（URL取得→ドラフト→レビュー依頼→修正→最終版）全体が収まるよう 15 分に設定。
# 短いと request_review 完了後に ProcessTransport is not ready for writing で落ちる。
# 参照: anthropics/claude-agent-sdk-python#676
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "900000")

# このモジュールで使うロガー名（log/article_agent_*.log に出力される）
LOGGER_NAME_ARTICLE = "article_agent"

# -----------------------------------------------------------------------------
# 定数
# -----------------------------------------------------------------------------

# CLI で URL 未入力時に使うデフォルトの対象 URL
DEFAULT_URL = "https://zenn.dev/tmtk/articles/624b98c6a52f09"
# 最終版として受け付ける最小文字数。これ未満の場合は「記事が得られなかった」として ValueError
MIN_CONTENT_LENGTH = 50


# -----------------------------------------------------------------------------
# ツールと MCP サーバ（レビュー依頼）
# -----------------------------------------------------------------------------

@tool(
    "request_review",
    REQUEST_REVIEW_TOOL_DESCRIPTION,
    {"draft_text": str},
)
async def request_review(args: dict[str, Any]) -> dict[str, Any]:
    """Claude が呼び出すツール。ドラフトを A2A でレビューエージェントに送り、フィードバック文字列を返す。"""
    draft_text = args.get("draft_text") or ""
    if not draft_text.strip():
        raise ValueError("request_review には空でない draft_text を指定してください。")
    logger = logging.getLogger(LOGGER_NAME_ARTICLE)
    logger.info("request_review called draft_len=%s", len(draft_text))
    try:
        review = await a2a_review(draft_text)
        logger.info("request_review completed result_len=%s", len(review))
        return {"content": [{"type": "text", "text": review}]}
    except Exception:
        logger.exception("request_review failed")
        raise


review_mcp_server = create_sdk_mcp_server(
    name="article_review",
    version="1.0.0",
    tools=[request_review],
)


# -----------------------------------------------------------------------------
# CLI 入力
# -----------------------------------------------------------------------------


def read_multiline(prompt: str) -> str:
    """プロンプトを表示し、空行が入力されるまで行を読み取り、結合した文字列を返す。"""
    print(prompt)
    print("（入力終了は空行を1行入力）")
    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


# -----------------------------------------------------------------------------
# 記事作成フロー
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


def _process_stream_message(msg: Any, result_text: str, logger: logging.Logger) -> str:
    """
    query() が返すストリームメッセージを 1 件処理し、更新後の result_text を返す。
    - AssistantMessage / ResultMessage: ログと画面の両方に内容を出す。
    - その他（UserMessage / SystemMessage など）: ログにのみ内容を残し、画面には出さない。
    """
    if isinstance(msg, AssistantMessage):
        text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
        if text_parts:
            result_text = "\n".join(text_parts)
            logger.info("AssistantMessage: text_len=%s\ncontent=%s", len(result_text), result_text)
            print(result_text)
    elif isinstance(msg, ResultMessage):
        if msg.result:
            result_text = msg.result
            logger.info("ResultMessage: result_len=%s\ncontent=%s", len(result_text), result_text)
            print(result_text)
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


async def run_one_article_flow(url: str, user_prompt: str) -> None:
    """
    1 記事分の処理を実行する。
    URL と自由プロンプトに基づき記事ドラフトを作成し、レビューエージェントのフィードバックを
    反映してから最終版を output/ に保存する。レビュー回数は Claude の判断に任せる。
    """
    # 同一秒で複数実行しても上書きされないようタイムスタンプにマイクロ秒まで含める（レビューと共通形式）
    ts = get_log_timestamp()
    run_id = f"article_agent_{ts}"
    final_path = f"output/final_{ts}.md"
    logger = setup_article_agent_log(run_id)
    log_path = Path(LOG_DIR) / f"{run_id}.log"
    logger.info("run start url=%s user_prompt_len=%s", url, len(user_prompt or ""))

    # Playwright: URL 取得用。review: レビュー依頼ツール（A2A クライアントを内包）
    options = ClaudeAgentOptions(
        mcp_servers={
            "playwright": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest", "--headless", "--no-sandbox", "--browser=chromium"],
            },
            "review": review_mcp_server,
        },
        allowed_tools=[
            "mcp__playwright__*",
            "mcp__review__request_review",
            "Read",
            "Write",
            "Edit",
            "Bash",
        ],
        # Docker/CLI 非対話実行ではツール許可ストリームが閉じるため、ツールを自動許可する
        permission_mode="bypassPermissions",
    )

    try:
        validate_prompt_inputs(url, user_prompt)
        logger.info("validation passed")

        prompt = build_article_agent_prompt(url, user_prompt)

        print("\n--- 記事作成エージェントを開始（レビューはエージェントが自律的に依頼します）---\n")
        print(f"詳細ログ: {log_path}\n")

        logger.info("query start")

        # プロンプトは async generator で渡す。文字列で渡すと MCP 利用時に stdin が早く閉じ、
        # ProcessTransport エラーになるため（claude-agent-sdk-python#386 / PR #630 参照）。
        async def prompt_stream():
            yield {"type": "user", "message": {"role": "user", "content": prompt}}

        result_text = ""
        async for msg in query(prompt=prompt_stream(), options=options):
            result_text = _process_stream_message(msg, result_text, logger)

        logger.info("query end result_len=%s", len(result_text or ""))

        if not result_text or len(result_text.strip()) < MIN_CONTENT_LENGTH:
            raise ValueError(
                "記事作成エージェントから最終版が得られませんでした。"
                " URL・プロンプトやレビューエージェントの起動を確認してください。"
            )

        # 最終版を output/ に保存
        save_markdown(final_path, result_text)
        logger.info("saved path=%s", final_path)
        print("\n=== 完了 ===")
        print(f"- Final: {final_path}\n")
    except Exception:
        logger.exception("run failed")
        raise


# -----------------------------------------------------------------------------
# メインループとエントリポイント
# -----------------------------------------------------------------------------


async def main() -> None:
    """対話的に URL と自由プロンプトを入力し、1 記事ずつ run_one_article_flow を実行するループ。1 件失敗してもループは継続し、次の URL を入力できる。"""
    print("=== 記事作成エージェント（自由プロンプト入力）===")
    print("終了する場合は URL 入力で Ctrl+C またはプロセス終了してください。\n")

    while True:
        try:
            url = input(f"対象URL（未入力ならデフォルト: {DEFAULT_URL}）> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not url:
            url = DEFAULT_URL

        try:
            user_prompt = read_multiline("自由プロンプト（例：経営層向け/技術者向け/短め/用語に注釈 等）>")
        except (EOFError, KeyboardInterrupt):
            print("\n入力をスキップしました。")
            continue

        try:
            await run_one_article_flow(url, user_prompt)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            print(f"\nエラー: {e}\n詳細はログを確認してください。続けて次の URL を入力できます。\n")


def _cli() -> None:
    """エントリポイント。asyncio.run で main を実行する。"""
    asyncio.run(main())


if __name__ == "__main__":
    _cli()

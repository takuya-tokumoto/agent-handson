"""
記事作成エージェント（メインエントリポイント）。

Claude Agent SDK と MCP（Playwright / レビュー依頼ツール）で URL を読み、
レビューエージェント（A2A）とやり取りしながら記事を完成させ、最終版を output/ に保存する。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions, tool, create_sdk_mcp_server
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
from tools_action_manager import save_markdown, a2a_review
from prompts import REQUEST_REVIEW_TOOL_DESCRIPTION, build_article_agent_prompt

load_dotenv()

DEFAULT_URL = "https://zenn.dev/tmtk/articles/624b98c6a52f09"
MIN_CONTENT_LENGTH = 50


@tool(
    "request_review",
    REQUEST_REVIEW_TOOL_DESCRIPTION,
    {"draft_text": str},
)
async def request_review(args: dict[str, Any]) -> dict[str, Any]:
    draft_text = args.get("draft_text") or ""
    if not draft_text.strip():
        raise ValueError("request_review には空でない draft_text を指定してください。")
    review = await a2a_review(draft_text)
    return {"content": [{"type": "text", "text": review}]}


# 記事作成エージェントがレビューを依頼するための MCP サーバ（同一プロセス内）
review_mcp_server = create_sdk_mcp_server(
    name="article_review",
    version="1.0.0",
    tools=[request_review],
)


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


async def run_one_article_flow(url: str, user_prompt: str) -> None:
    """1記事分の処理。記事作成エージェントがレビューツールを必要なだけ呼び、自律的に完成版を出す。"""
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = f"output/final_{now}.md"

    options = ClaudeAgentOptions(
        mcp_servers={
            "playwright": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest", "--headless", "--no-sandbox"],
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
    )

    prompt = build_article_agent_prompt(url, user_prompt)

    print("\n--- 記事作成エージェントを開始（レビューはエージェントが自律的に依頼します）---\n")

    result_text = ""
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
            if text_parts:
                result_text = "\n".join(text_parts)
                print(result_text[:300], "..." if len(result_text) > 300 else "")
        elif isinstance(msg, ResultMessage):
            if msg.result:
                result_text = msg.result

    if not result_text or len(result_text.strip()) < MIN_CONTENT_LENGTH:
        raise ValueError(
            "記事作成エージェントから最終版が得られませんでした。"
            " URL・プロンプトやレビューエージェントの起動を確認してください。"
        )

    save_markdown(final_path, result_text)
    print("\n=== 完了 ===")
    print(f"- Final: {final_path}\n")


async def main() -> None:
    """CLI ループ: URL と自由プロンプトを入力し、1 記事ずつ run_one_article_flow を実行する。"""
    print("=== 記事作成エージェント（自由プロンプト入力）===")
    print("終了する場合は URL 入力で Ctrl+C またはプロセス終了してください。\n")

    while True:
        url = input(f"対象URL（未入力ならデフォルト: {DEFAULT_URL}）> ").strip()
        if not url:
            url = DEFAULT_URL

        user_prompt = read_multiline("自由プロンプト（例：経営層向け/技術者向け/短め/用語に注釈 等）>")

        await run_one_article_flow(url, user_prompt)


def _cli() -> None:
    """エントリポイント。asyncio で main を実行する。"""
    asyncio.run(main())


if __name__ == "__main__":
    _cli()

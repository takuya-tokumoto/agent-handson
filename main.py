from __future__ import annotations

import asyncio
from datetime import datetime

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
from tools_action_manager import save_markdown, a2a_review

DEFAULT_URL = "https://zenn.dev/tmtk/articles/624b98c6a52f09"

BASE_INSTRUCTION = """
あなたは社内向けの「記事作成エージェント」です。
目的：指定URLを読み、Confluence貼り付け用のMarkdown記事を作成する。

必須要件：
- 見出しと箇条書きを多用して読みやすく
- 最低でも次のセクションを含める：
  - 要約
  - 重要ポイント
  - 参考リンク（参照元URLを必ず含める）
  - 次アクション（社内での活用・検討観点）
- 出力は日本語
- Web閲覧は Playwright MCP を使う（必要最低限のアクセス回数で）
"""

REVISION_INSTRUCTION = """
あなたは社内向け記事の編集者です。
与えられた「ドラフト」と「レビュー結果」をもとに、Confluence貼り付け用Markdownとして改善した最終版を出力してください。

必須要件：
- 「レビュー結果」で指摘された不足セクションや改善点を反映
- 文章量が極端に増えないように、重要なところだけ改善
- 参考リンクは維持し、必要なら増やす（一次ソース優先）
"""

def read_multiline(prompt: str) -> str:
    print(prompt)
    print("（入力終了は空行を1行入力）")
    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()

async def run_agent(prompt: str, options: ClaudeAgentOptions) -> str:
    result_text = ""
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
            if text_parts:
                result_text = "\n".join(text_parts)
                print(result_text[:200], "..." if len(result_text) > 200 else "")
        elif isinstance(msg, ResultMessage):
            if msg.result:
                result_text = msg.result
    return result_text

async def main():
    # Playwright MCP（外部MCP：stdio）
    options = ClaudeAgentOptions(
        mcp_servers={
            "playwright": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest", "--headless"],
            }
        },
        allowed_tools=[
            "mcp__playwright__*",
            "Read", "Write", "Edit", "Bash",
        ],
    )

    print("=== 記事作成エージェント（自由プロンプト入力）===")
    print("終了する場合は URL 入力で Ctrl+C またはプロセス終了してください。\n")

    while True:
        url = input(f"対象URL（未入力ならデフォルト: {DEFAULT_URL}）> ").strip()
        if not url:
            url = DEFAULT_URL

        user_prompt = read_multiline("自由プロンプト（例：経営層向け/技術者向け/短め/用語に注釈 等）>")

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        draft_path = f"output/draft_{now}.md"
        final_path = f"output/final_{now}.md"

        # 1) ドラフト生成（Playwright MCP を使って読む）
        draft_prompt = f"""{BASE_INSTRUCTION}

対象URL: {url}

ユーザー要望（自由プロンプト）:
{user_prompt if user_prompt else "(指定なし)"}

出力は「完成したMarkdown本文のみ」を返してください。
"""
        print("\n--- ドラフト生成を開始 ---\n")
        draft_text = await run_agent(draft_prompt, options)

        save_markdown(draft_path, draft_text)

        # 2) A2Aでレビュー
        print("\n--- A2Aレビューを開始 ---\n")
        review_text = await a2a_review(draft_text)

        # 3) レビュー反映して最終版生成（Web閲覧は不要なので同じoptionsでOK）
        revise_prompt = f"""{REVISION_INSTRUCTION}

対象URL: {url}

ドラフト:
{draft_text}

レビュー結果:
{review_text}

出力は「完成したMarkdown本文のみ」を返してください。
"""
        print("\n--- 最終版生成を開始 ---\n")
        final_text = await run_agent(revise_prompt, options)

        save_markdown(final_path, final_text)

        print("\n=== 完了 ===")
        print(f"- Draft : {draft_path}")
        print(f"- Final : {final_path}\n")

def _cli():
    asyncio.run(main())

if __name__ == "__main__":
    _cli()

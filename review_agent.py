import os
import re
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.client import create_text_message_object
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Role

REQUIRED_SECTIONS = ["要約", "重要ポイント", "参考リンク", "次アクション"]

def simple_review(text: str) -> str:
    findings = []
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            findings.append(f"- セクション不足: 「{sec}」を追加すると読みやすい")
    if len(text) < 600:
        findings.append("- 文字数が短め：背景/結論/根拠をもう少し足すと社内共有に強い")
    if not re.search(r"https?://", text):
        findings.append("- 参考リンクが見当たりません：一次ソースURLを最低1つ入れるのがおすすめ")
    if not findings:
        findings.append("- 大きな不足は見当たりません。タイトルと結論が明確で良いです。")
    return "A2Aレビュー結果（自動）:\n" + "\n".join(findings)

class ReviewExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or "(テキスト取得に失敗しました)"
        review_msg = create_text_message_object(role=Role.agent, content=simple_review(user_text))
        await event_queue.enqueue_event(review_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")

def build_agent_card(base_url: str) -> AgentCard:
    skill = AgentSkill(
        id="review_draft",
        name="レビュー（Confluenceドラフト）",
        description="Confluence向けドラフトの不足セクションと改善点をチェックします。",
        tags=["review", "checklist", "confluence"],
        examples=["このドラフトをレビューして", "不足セクションを指摘して"],
    )
    return AgentCard(
        name="レビューエージェント",
        description="ドラフトをレビューしてチェックリストを返すA2Aエージェント。",
        url=base_url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )

def _cli():
    host = "0.0.0.0"
    port = 9999
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

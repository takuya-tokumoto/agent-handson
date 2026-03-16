"""
A2A クライアントによるレビュー依頼と、Markdown 保存のユーティリティ。

記事作成エージェントの request_review ツールから a2a_review() を呼び出し、
レビューエージェント（A2A サーバ）にドラフトを送信してレビュー結果テキストを取得する。
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
from a2a.client import A2AClient, A2ACardResolver, create_text_message_object
from a2a.types import MessageSendParams, SendMessageRequest

# A2A 通信のタイムアウト（秒）
A2A_HTTP_TIMEOUT = 60.0


def _extract_texts_from_a2a_response(dumped: dict) -> list[str]:
    """A2A レスポンスの result からテキスト部分を抽出する。解析に失敗した場合は例外を送出する。"""
    result = dumped.get("result", {})
    parts = result.get("parts") or result.get("status", {}).get("message", {}).get("parts", [])
    texts: list[str] = []
    for p in parts:
        if p.get("kind") == "text" and "text" in p:
            texts.append(p["text"])
    return texts


def save_markdown(path: str, content: str) -> str:
    """指定パスに Markdown 本文を書き込む。output/ は存在しなければ作成する。"""
    Path("output").mkdir(parents=True, exist_ok=True)
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    return f"Saved: {p.resolve()}"


async def a2a_review(draft_text: str, a2a_base_url: str | None = None) -> str:
    """
    レビューエージェント（A2A サーバ）にドラフトを送信し、レビュー結果テキストを取得する。

    環境変数 A2A_BASE_URL が未設定の場合は http://localhost:9999 を使用する。
    レスポンスからテキストを抽出できない場合は ValueError を送出する。
    """
    if a2a_base_url is None:
        a2a_base_url = os.environ.get("A2A_BASE_URL", "http://localhost:9999")
    async with httpx.AsyncClient(timeout=A2A_HTTP_TIMEOUT) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=a2a_base_url)
        agent_card = await resolver.get_agent_card()
        client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)

        message = create_text_message_object(content=draft_text)
        req = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(message=message),
        )
        resp = await client.send_message(req)
        dumped = resp.model_dump(mode="json", exclude_none=True)

        texts = _extract_texts_from_a2a_response(dumped)
        if not texts:
            raise ValueError(
                "A2Aレスポンスからテキストを取得できませんでした。"
                f" response={dumped}"
            )
        return "\n".join(texts)

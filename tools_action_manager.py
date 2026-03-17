"""
A2A クライアントによるレビュー依頼と、Markdown 保存のユーティリティ。

- a2a_review(draft_text): レビューエージェント（A2A サーバ）にドラフトを送り、レビュー文を取得する。
  main.py の request_review ツールから呼ばれる。接続先は環境変数 A2A_BASE_URL（未設定時は localhost:9999）。
- save_markdown(path, content): 指定パスに Markdown を書き出す。output/ 用。
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
from a2a.client import A2AClient, A2ACardResolver, create_text_message_object
from a2a.types import MessageSendParams, SendMessageRequest

# A2A の HTTP リクエスト（GetAgentCard / SendMessage）のタイムアウト（秒）
A2A_HTTP_TIMEOUT = 60.0


# -----------------------------------------------------------------------------
# A2A レスポンス解析（内部用）
# -----------------------------------------------------------------------------


def _extract_texts_from_a2a_response(dumped: dict) -> list[str]:
    """
    A2A の SendMessage レスポンスからテキスト部分を抽出する。
    レスポンス構造: result.parts[] または result.status.message.parts[] に kind="text" の要素が含まれる。
    該当なしの場合は空リストを返す。result が None や非 dict のときも安全に空リストを返す。
    """
    result = dumped.get("result")
    if result is None or not isinstance(result, dict):
        return []
    parts = result.get("parts") or ((result.get("status") or {}).get("message") or {}).get("parts", [])
    if not isinstance(parts, list):
        parts = []
    texts: list[str] = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("kind") == "text" and "text" in p:
            texts.append(p["text"])
    return texts


# -----------------------------------------------------------------------------
# ファイル保存
# -----------------------------------------------------------------------------


def save_markdown(path: str, content: str) -> str:
    """指定パスに Markdown 本文を UTF-8 で書き込む。親ディレクトリが無ければ作成する。戻り値は保存した絶対パスのメッセージ。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Saved: {p.resolve()}"


# -----------------------------------------------------------------------------
# A2A レビュー依頼
# -----------------------------------------------------------------------------


async def a2a_review(draft_text: str, a2a_base_url: str | None = None) -> str:
    """
    レビューエージェント（A2A サーバ）にドラフトを送信し、レビュー結果のテキストを取得する。

    - 接続先: 引数 a2a_base_url が None のときは環境変数 A2A_BASE_URL を使用し、
      未設定なら http://localhost:9999 。（Docker からホストのレビューエージェントに繋ぐ場合は
      A2A_BASE_URL=http://host.docker.internal:9999 などを指定する。）
    - レスポンスからテキストを抽出できない場合は ValueError を送出する。
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

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
from a2a.client import A2AClient, A2ACardResolver, create_text_message_object
from a2a.types import MessageSendParams, SendMessageRequest, Message

def save_markdown(path: str, content: str) -> str:
    Path("output").mkdir(parents=True, exist_ok=True)
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    return f"Saved: {p.resolve()}"

async def a2a_review(draft_text: str, a2a_base_url: str | None = None) -> str:
    if a2a_base_url is None:
        a2a_base_url = os.environ.get("A2A_BASE_URL", "http://localhost:9999")
    async with httpx.AsyncClient() as httpx_client:
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

        texts = []
        try:
            result = dumped.get("result", {})
            # result is Message (kind=message) or Task
            parts = result.get("parts") or result.get("status", {}).get("message", {}).get("parts", [])
            for p in parts:
                if p.get("kind") == "text" and "text" in p:
                    texts.append(p["text"])
        except Exception:
            pass

        if texts:
            return "\n".join(texts)

        return str(dumped)

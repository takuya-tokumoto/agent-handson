
# 04_03_ハンズオンシナリオ案
### 社内Tech News⾃動まとめエージェント（Claude Agent SDK × MCP × A2A）

### 目的
*   実行時にユーザーが指示（プロンプト）して記事作成を依頼する
*   Playwright MCP を使ってWeb記事を読みに⾏き、記事ドラフトを生成する
*   レビューエージェント（A2A）にレビューさせ、改善した最終版を出力する

### 1. 環境構築（Windows + WSL2 Ubuntu22.04 前提）

#### 1.1 管理者権限の取得
WSLをインストールするために管理者権限が必要です。情シスへ申請し、反映まで1日程度見込んでください。
1.  [https://ariseanalytics.atlassian.net/servicedesk/customer/portal/2/group/13/create/31](https://ariseanalytics.atlassian.net/servicedesk/customer/portal/2/group/13/create/31)にアクセス
2.  シンARISE-PC, その他にチェックして備考欄にWSLのインストールと記載

#### 1.2 WSL2 Ubuntu22.04 のインストール
1.  Windows PowerShell を **管理者権限** で開く
2.  以下を実行
    ```bash
    wsl --install -d Ubuntu-22.04
    ```
3.  Ubuntu初回起動時にユーザー名とパスワードを任意の値で設定（忘れないように）
4.  再起動して PowerShell を開き、以下を実行
    ```bash
    wsl -l -v
    ```
5.  `NAME` が `Ubuntu-22.04`、`VERSION` が `2` であることを確認

#### 1.3 DNS の設定（重要）
WSLのデフォルトネットワーク設定が環境依存で特殊になっている場合があり、Docker動作等へ影響します。一般的なLinuxと同等の設定になるよう変更します。
1.  Ubuntu22.04 を開く（アプリ検索 or PowerShellタブの▽から起動）
2.  以下を実行
    ```bash
    sudo vim /etc/wsl.conf
    ```
3.  `i` を押して挿入モードにし、以下を追記
    ```
    [network]
    generateResolvConf=false
    ```
    ※ `false` の `f` は小文字
4.  `ESC` → `:wq` で保存
5.  以下を実行
    ```bash
    sudo rm /etc/resolv.conf
    sudo sh -c "echo 'nameserver 8.8.8.8' > /etc/resolv.conf"
    cat /etc/resolv.conf
    ```
6.  `nameserver 8.8.8.8` になっていることを確認
7.  任意で疎通確認
    ```bash
    curl https://www.google.com
    ```

#### 1.4 Docker のインストール（Ubuntu側に Docker Engine）
1.  一行ずつ実行：
    ```bash
    sudo apt-get update
    sudo apt-get install ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    ```
2.  まとめて一回で実行：
    ```bash
    echo \
      "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    ```
3.  一行ずつ実行：
    ```bash
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo systemctl start docker
    ```
4.  `Hello from Docker` のような表示が出たら完了
    ```bash
    sudo docker run hello-world
    ```

#### 1.5 Docker グループ設定
1.  一行ずつ実行：
    ```bash
    sudo groupadd docker
    sudo usermod -aG docker $USER
    ```
2.  Ubuntu を再起動（権限変更反映のため）
3.  以下を実行して確認：
    ```bash
    docker run hello-world
    ```

### 2. ハンズオン：記事作成エージェント（自由プロンプト入力）
※各自dockerコンテナを用意するなどしてPC環境を破壊しないように注意してください

#### 2.1 前提（WSL2 / Linux 共通）
*   Docker Engine（WSL上）と docker compose が使えること
*   以降の作業は WSL上のディレクトリで行うこと（Windows側ではなくUbuntu側）

#### 2.2 プロジェクト作成（ホスト側：WSL）

##### 2.2.1 作業ディレクトリ作成
Ubuntu（WSL）で以下を実行：
```bash
mkdir -p agent-handson && cd agent-handson
```

##### 2.2.2 `.env` を作る（APIキーはここに置く）
`agent-handson/.env` を作成し、以下のどちらか（または両方）を設定します。

A) Anthropic API を使う場合  

以下を実行して`.env`を作成
```bash
cp .env.sample .env
```

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx

# モデル指定（共通）
# 例. ANTHROPIC_MODEL
# 例. ANTHROPIC_MODEL=claude-3-5-sonnet-latest
ANTHROPIC_MODEL=xxx
```

B) Amazon Bedrock（API Key / Bearer token）を使う場合
```
# Bedrock経由で動かすフラグ（Claude Code/Agent SDK側が参照）
CLAUDE_CODE_USE_BEDROCK=1

# Bedrockのリージョン（例）
AWS_REGION=ap-northeast-1

# Bedrock API key（Bearer token）
AWS_BEARER_TOKEN_BEDROCK=xxxxxxxxxxxxxxxx

# モデル指定（共通）
# 例. ANTHROPIC_MODEL=apac.anthropic.claude-sonnet-4-20250514-v1:0
ANTHROPIC_MODEL=xxxx
```
`.env` は機密情報です。Gitにコミットしないよう `.gitignore` を設定します（後述）。

##### 2.2.3 ファイル構成
この構成でファイルを作ります：
```
agent-handson/
  .env
  .gitignore       (任意)
  Dockerfile
  requirements.txt
  main.py
  tools_action_manager.py
  output/          (生成物)
```

#### 2.3 Dockerイメージを作る（Dockerfile）

##### 2.3.1 requirements.txt
`agent-handson/requirements.txt`
```
claude-agent-sdk
a2a-sdk[http-server]
httpx
python-dotenv
uvicorn
```

##### 2.3.2 Dockerfile
Playwright MCP を `npx` で起動するため Node.js が必要です。
また、Web閲覧を安定させるために Playwright公式イメージをベースにします（ブラウザ依存が揃っているため）。
`agent-handson/Dockerfile`
```dockerfile
# Playwright公式イメージ（ブラウザ実行に必要な依存が揃っている）
FROM mcr.microsoft.com/playwright:v1.58.2-jammy

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Python環境（Ubuntu 22.04ベースなのでpython3はあるが、pip等を確実にする）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# 依存関係
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r /app/requirements.txt

# アプリ本体はマウント運用でも良いが、ここでは一応COPYも可能にしておく
COPY . /app

# デフォルトはシェル（必要なら main.py にしてもOK）
CMD ["bash"]
```

#### 2.4 実装（Pythonファイルを作成）

##### 2.4.1 レビューエージェント（A2Aサーバ） review_agent.py
`agent-handson/review_agent.py`
```python
import re
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

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
        user_text = ""
        try:
            parts = context.request.params.message.parts  # type: ignore
            user_text = "\n".join([p.text for p in parts if getattr(p, "kind", None) == "text"])
        except Exception:
            user_text = "(テキスト取得に失敗しました)"

        review = simple_review(user_text)

        # サーバ側に出す（デモで分かりやすい）
        print("\n[review_agent] review result:\n" + review + "\n")

        await event_queue.enqueue_event(new_agent_text_message(review))

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

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 9999
    base_url = f"http://localhost:{port}/"

    agent_card = build_agent_card(base_url)
    request_handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(),
        task_store=InMemoryTaskStore()
    )
    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    uvicorn.run(server.build(), host=host, port=port)
```

##### 2.4.2 A2Aクライアント & 保存 tools_action_manager.py
`agent-handson/tools_action_manager.py`
```python
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import MessageSendParams, SendMessageRequest


def save_markdown(path: str, content: str) -> str:
    Path("output").mkdir(parents=True, exist_ok=True)
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    return f"Saved: {p.resolve()}"


async def a2a_review(draft_text: str, a2a_base_url: str | None = None) -> str:
    base = a2a_base_url or os.getenv("REVIEW_AGENT_URL", "http://localhost:9999")

    async with httpx.AsyncClient() as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base)
        agent_card = await resolver.get_agent_card()
        client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)

        payload = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": draft_text}],
                "messageId": uuid4().hex,
            }
        }
        req = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(**payload))
        resp = await client.send_message(req)
        dumped = resp.model_dump(mode="json", exclude_none=True)

        texts = []
        try:
            parts = dumped.get("result", {}).get("message", {}).get("parts", [])
            for p in parts:
                if p.get("kind") == "text" and "text" in p:
                    texts.append(p["text"])
        except Exception:
            pass

        return "\n".join(texts) if texts else str(dumped)
```

##### 2.4.3 記事作成エージェント（自由プロンプト入力CLI） main.py
`agent-handson/main.py`
```python
from __future__ import annotations

import os
import re
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from claude_agent_sdk import query, ClaudeAgentOptions
from tools_action_manager import save_markdown, a2a_review

DEFAULT_FALLBACK_TOPIC = "エージェント開発（Claude Agent SDK / MCP / A2A）の要点"

BASE_INSTRUCTION = """
あなたは社内向けの「Tech News自動まとめエージェント」です。
入力（ユーザー依頼）をもとに、Confluence貼り付け用のMarkdown記事を作成してください

【入力のルール】
- ユーザー依頼文に URL が含まれる場合：そのURLを優先して読み、記事化する
- URL が含まれない場合：Web検索して一次ソースを探し、最大3件の情報源を読んで記事化する
  - 検索は WebFetch を使ってよい（検索結果ページを取得）
  - 本文を読むのは Playwright MCP を優先（必要最低限のアクセス回数で）
  - 参照したURLは必ず「参考リンク」に残す

【必須セクション】
- 要約
- 重要ポイント（箇条書き）
- 参考リンク（参照したURLを必ず含める）
- 次アクション（社内での活用・検討観点）

【スタイル】
- 日本語
- 見出しと箇条書きを多用して読みやすく
- 断定しすぎず、根拠（リンク）に基づいて書く
"""

REVISION_INSTRUCTION = """
あなたは社内向け記事の編集者です。
与えられた「ドラフト」と「レビュー結果」をもとに、Confluence貼り付け用Markdownとして修正してください

必須要件：
- 「レビュー結果」で指摘された不足セクションや改善点を反映
- 文章量が極端に増えないように、重要なところだけ改善
- 参考リンクは維持し、必要なら増やす（一次ソース優先）
"""

URL_RE = re.compile(r"https?://[^\s)>\"]+")


def ensure_credentials_and_print_model() -> None:
    anthropic = os.getenv("ANTHROPIC_API_KEY")
    bedrock_token = os.getenv("AWS_BEARER_TOKEN_BEDROCK")

    if not anthropic and not bedrock_token:
        raise RuntimeError(
            "認証情報が見つかりません。.env に ANTHROPIC_API_KEY または AWS_BEARER_TOKEN_BEDROCK を設定してください。"
        )

    # Bedrockトークンがあるのに Bedrockフラグが無い場合は補う（ミス防止）
    if bedrock_token and not os.getenv("CLAUDE_CODE_USE_BEDROCK"):
        os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"

    model = os.getenv("ANTHROPIC_MODEL")
    if model:
        print(f"[INFO] ANTHROPIC_MODEL={model}")
    else:
        print("[WARN] ANTHROPIC_MODEL が未設定です。.env でモデル指定することを推奨します。")


def read_multiline_one_input() -> str:
    print("依頼を1つ入力してください（URLを含めてもOK / 空行で終了）")
    lines = []
    while True:
        line = input()
        if line.strip() == "":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    return text if text else DEFAULT_FALLBACK_TOPIC


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text)


def _text_from_msg(msg) -> str:
    if isinstance(msg, str):
        return msg

    subtype = getattr(msg, "subtype", None)
    if subtype == "init":
        return ""

    content = getattr(msg, "content", None)
    if content and isinstance(content, list):
        parts = []
        for b in content:
            t = getattr(b, "text", None)
            if t:
                parts.append(t)
        if parts:
            return "\n".join(parts)

    t = getattr(msg, "text", None)
    if t:
        return str(t)

    return ""


async def run_agent_stream_text(prompt: str, options: ClaudeAgentOptions) -> str:
    out = []
    async for msg in query(prompt=prompt, options=options):
        text = _text_from_msg(msg)
        if text:
            print(text, flush=True)
            out.append(text)
    return "\n".join(out).strip()


async def main():
    ensure_credentials_and_print_model()

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
            "WebFetch",
            "Read",
            "Write",
            "Edit",
            "Bash",
        ],
    )

    print("=== 記事作成エージェント（入力は1つ）===")

    user_request = read_multiline_one_input()
    urls = extract_urls(user_request)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft_path = f"output/draft_{now}.md"
    final_path = f"output/final_{now}.md"

    if urls:
        context_line = "優先URL:\n" + "\n".join(f"- {u}" for u in urls[:3])
    else:
        context_line = "URL指定なし（Web検索して一次ソース最大3件で記事化）"

    draft_prompt = f"""{BASE_INSTRUCTION}


ユーザー依頼:
{user_request}

補足:
{context_line}

出力は「完成したMarkdown本文のみ」を返してください。
"""

    try:
        print("\n--- ドラフト生成（逐次表示） ---\n")
        draft_text = await run_agent_stream_text(draft_prompt, options)
        save_markdown(draft_path, draft_text)

        print("\n--- A2Aレビュー ---\n")

### **2.5 Dockerイメージのビルド（WSLターミナル）**

`agent-handson` ディレクトリで：

```markdown
docker build -t agent-handson:latest .
```

### **2.6 実⾏（コンテナで2プロセス動かす）**

#### 2.6.1 ターミナル1：レビューエージェント起動（コンテナ）

```markdown
docker run --rm -it \
  --env-file ./.env \
  -p 9999:9999 \
  -v "$PWD:/app" \
  -w /app \
  agent-handson:latest \
  python3 review_agent.py
```

確認（任意、別ターミナルで）：

```markdown
curl http://localhost:9999/.well-known/agent-card.json
```

#### 2.6.2 ターミナル2：記事作成エージェント起動（コンテナ）

```markdown
docker run --rm -it \
  --env-file ./.env \
  -v "$PWD:/app" \
  -w /app \
  agent-handson:latest \
  python3 main.py
```

⽣成物：
`output/draft_YYYYMMDD_HHMMSS.md`
`output/final_YYYYMMDD_HHMMSS.md`
※ `-v "$PWD:/app"` でホストのフォルダをマウントしているため、⽣成物はホスト側 `agent-handson/output/` に残ります。

### **3. 解説**

#### **3.1 全体アーキテクチャ**

このシステムは⼤きく5つの要素で構成

1.  **記事作成エージェント `main.py`**
    ユーザー⼊⼒を受け取り、LLMと対話してドラフト→最終版を⽣成
2.  **レビューエージェント `review_agent.py`**
    A2Aサーバとして動作し、ドラmain.py`**
    ユーザー⼊⼒を受け取り、LLMと対話してドラフト→最終版を⽣成
2.  **レビューエージェント `review_agent.py`**
    A2Aサーバとして動作し、ドラフトをチェックして改善点を返す
3.  **Claude Agent SDK** (`claude-agent-sdk`) (ライブラリ)
    LLMとの対話・ツール呼び出し・MCPサーバ管理を担う中核
    *要素* / *対応ファイル* / *役割*
4.  **Playwright MCP** (`@playwright/mcp`) (npmパッケージ)
    ヘッドレスブラウザでWebページを閲覧する
5.  **A2Aクライアント** (`tools_action_manager.py`)
    レビューエージェントにHTTPでドラフトを送信

#### **3.2 処理フロー（シーケンス図）**

##### Phase 1：ドラフト⽣成

1.  ユーザーがCLIからプロンプトを⼊⼒（URLを含めてもOK）
2.  `main.py` が Claude Agent SDK の `query` 関数を呼び出し、LLMと対話を開始
3.  LLMが必要と判断した場合、Playwright MCP 経由でWebページにアクセスし、記事の内容を取得
4.  取得した情報をもとに、Markdown形式のドラフトを⽣成し、 `output/draft_*.md` として保存

##### Phase 2：A2Aレビュー

5.  ⽣成されたドラフトを A2Aクライアント が HTTP POST で レビューエージェント（Port 9999）に送信
6.  レビューエージェントは必須セクションの有無・⽂字数・参考リンクの有無をチェックし、改善点をテキストで返す

##### Phase 3：最終版⽣成

7.  ドラフトとレビュー結果を合わせて再度 Claude Agent SDK 経由でLLMに投げ、改善版を⽣成
8.  最終版を `output/final_*.md` として保存

#### **3.3 各技術の役割と該当コード**

##### **3.3.1 Claude Agent SDK ̶ エージェントの「頭脳」**

Claude Agent SDK は、このシステム全体の中核
LLM（Claude）との対話、ツールの管理、MCPサーバの起動をすべてこのSDKが担う

##### ① LLMとの対話（query関数）

`main.py` の以下の部分で、Claude Agent SDK の `query` 関数を使ってLLMとやり取り

```python
# main.py（12⾏⽬）
from claude_agent_sdk import query, ClaudeAgentOptions

# main.py（114-121⾏⽬）
async def run_agent_stream_text(prompt: str, options: ClaudeAgentOptions) -> str:
    out = []
    async for msg in query(prompt=prompt, options=options):
        text = _text_from_msg(msg)
        if text:
            print(text, flush=True)  # ストリーミング表⽰
            out.append(text)
    return "\n".join(out).strip()
```

ポイントは `async for msg in query(...)` の部分。 `query` はジェネレータとして動作し、LLMからの応答をストリーミングで1メッセージずつ受け取る。これにより、⽣成途中の⽂章がリアルタイムに画⾯に表⽰される。

##### ② MCPサーバの管理

`ClaudeAgentOptions` の `mcp_servers` パラメータで、どのMCPサーバを使うかを宣⾔的に指定。

```python
# main.py（127-143⾏⽬）
options = ClaudeAgentOptions(
    mcp_servers={
        "playwright": {                              # ← MCPサーバ名
            "type": "stdio",                          # ← 通信⽅式（標準⼊出⼒）
```

`mcp_servers` に設定を書くだけで、SDK が⾃動的に Playwright MCP サーバをサブプロセスとして起動し、stdio （標準⼊出⼒）経由で通信可能に。開発者はブラウザの起動・管理を⼀切意識する必要なし。

##### ③ ツール権限制御（allowed_tools）

`allowed_tools` でLLMが使えるツールを明⽰的に制限。 `"mcp__playwright__*"` のようにワイルドカード指定することで、Playwright MCPが提供するすべてのツール（ページ遷移、テキスト取得、スクリーンショットなど）をまとめて許可。

##### **3.3.2 MCP（Model Context Protocol） ̶ ツール連携の「標準規格」**

MCP は、LLMが外部ツール（ブラウザ、ファイルシステム、データベースなど）と連携するための標準プロトコル。このハンズオンでは Playwright MCP を使って、LLMにWebブラウザ操作の能⼒を与えている。

##### MCPの動作の仕組み

MCPの通信は以下のように動作。
具体的には、SDK の `mcp_servers` 設定に基づいて以下が⾃動で実⾏。

1.  **サーバ起動**: `npx @playwright/mcp@latest --headless` が⼦プロセスとして起動される
2.  **ツール発⾒**: MCP の `tools/list` メッセージにより、利⽤可能なツール⼀覧が⾃動取得される (`mcp__playwright__navigate`, `mcp__playwright__snapshot` など)
3.  **ツール呼び出し**: LLMが「このURLを読みたい」と判断すると、SDK が MCP の `tools/call` メッセージを送り、Playwright がブラウザを操作してページ内容を返す

```python
6             "command": "npx",                         # ← 起動コマンド
7             "args": ["-y", "@playwright/mcp@latest", "--headless"],
8         }
9     },
10    allowed_tools=[
11        "mcp__playwright__*",  # ← Playwright MCPの全ツールを許可
12        "WebFetch",            # ← Web取得（組み込みツール）
13        "Read",                # ← ファイル読み込み
14        "Write",               # ← ファイル書き込み
15        "Edit",                # ← ファイル編集
16        "Bash",                # ← シェルコマンド実⾏
17    ],
18)
```

```mermaid
graph TD
    A[Claude Agent SDK（親プロセス）] -- stdio（標準⼊出⼒）で通信 --> B[Playwright MCP Server（⼦プロセス）]
    B -- Playwrightライブラリ --> C[ヘッドレスChromiumブラウザ]
    C -- HTTP --> D[Webサイト]
```

##### **3.3.3 A2A（Agent-to-Agent Protocol） ̶ エージェント間の「共通⾔語」**

A2A は、Google が提唱するエージェント間通信のオープンプロトコル。異なるフレームワークで作られたエージェント同⼠が、HTTP経由で協調作業できるようになる。

このハンズオンでは「レビューエージェント」を A2A サーバとして独⽴プロセスで動かし、記事作成エージェントから呼び出している。

##### ① A2Aサーバ側（review_agent.py）

A2Aサーバは3つの要素で構成されます。

**(a) エージェントカード ̶ ⾃分の能⼒を宣⾔するメタデータ**

エージェントカードは `http://localhost:9999/.well-known/agent-card.json` で公開され、クライアントはこれを読んで「このエージェントが何をできるか」を事前に知ることができる。

```python
# review_agent.py（48-65⾏⽬）
def build_agent_card(base_url: str) -> AgentCard:
    skill = AgentSkill(
        id="review_draft",
        name="レビュー（Confluenceドラフト）",
        description="Confluence向けドラフトの不⾜セクションと改善点をチェックします。",
        tags=["review", "checklist", "confluence"],
        examples=["このドラフトをレビューして", "不⾜セクションを指摘して"],
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
```

**(b) タスク実⾏ロジック ̶ 実際のレビュー処理**

今回はシンプルなルールベースのレビューだが、ここを別のLLMベースのエージェントに置き換えることも可能。ぜひ記事作成エージェントを参考にやってみてください。

```python
# review_agent.py（14-25⾏⽬）
REQUIRED_SECTIONS = ["要約", "重要ポイント", "参考リンク", "次アクション"]

def simple_review(text: str) -> str:
    findings = []
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            findings.append(f"- セクション不⾜: 「{sec}」を追加すると読みやすい")
    if len(text) < 600:
        findings.append("- ⽂字数が短め：背景/結論/根拠をもう少し⾜すと社内共有に強い")
    if not re.search(r"https?://", text):
        findings.append("- 参考リンクが⾒当たりません：⼀次ソースURLを最低1つ⼊れるのがお")
    if not findings:
        findings.append("- ⼤きな不⾜は⾒当たりません。タイトルと結論が明確で良いです。")
    return "A2Aレビュー結果（⾃動）:\n" + "\n".join(findings)
```

**(c) サーバ起動 ̶ UvicornでHTTPサーバとして起動**

```python
# review_agent.py（68-76⾏⽬）
if __name__ == "__main__":
    host = "0.0.0.0"
    port = 9999
    base_url = f"http://localhost:{port}/"
    agent_card = build_agent_card(base_url)
    request_handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(),
        task_store=InMemoryTaskStore()
    )
    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    uvicorn.run(server.build(), host=host, port=port)
```

##### ② A2Aクライアント側（tools_action_manager.py）

クライアント側は以下の⼿順でレビューを依頼

A2A通信のポイントは以下の3ステップです。

1.  **カード取得**： `/.well-known/agent-card.json` からエージェントの能⼒を確認
2.  **メッセージ送信**： `SendMessageRequest` でドラフトテキストを送る
3.  **結果受信**：レスポンスの `parts` からテキストを抽出

```python
# tools_action_manager.py（20-48⾏⽬）
async def a2a_review(draft_text: str, a2a_base_url: str | None = None) -> str:
    base = a2a_base_url or os.getenv("REVIEW_AGENT_URL", "http://localhost:9999")

    async with httpx.AsyncClient() as httpx_client:
        # 1. エージェントカードを取得（能⼒確認）
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base)
        agent_card = await resolver.get_agent_card()

        # 2. A2Aクライアントを初期化
        client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)

        # 3. メッセージを組み⽴てて送信
        payload = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": draft_text}],
                "messageId": uuid4().hex,
            }
        }
        req = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(**payload))
        resp = await client.send_message(req)

        # 4. レスポンスからテキストを抽出
        dumped = resp.model_dump(mode="json", exclude_none=True)
        # ... テキスト抽出処理 ...
```
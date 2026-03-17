"""
記事作成エージェント・レビューエージェント用のプロンプトと文言を一括定義する。

- 記事作成: ARTICLE_AGENT_INSTRUCTION（役割・手順）、build_article_agent_prompt()（URL・自由プロンプト付き）、
  REQUEST_REVIEW_TOOL_DESCRIPTION（ツール説明）、validate_prompt_inputs()（プロンプト入力の検証）
- レビュー: REVIEW_AGENT_INSTRUCTION（レビュー観点）、REVIEW_AGENT_* / REVIEW_SKILL_*（A2A エージェントカード用）

main.py / review_agent.py から import して利用。文言の変更はこのファイルだけ触ればよい。
"""
import re

# -----------------------------------------------------------------------------
# 記事作成エージェント用（入力検証）
# -----------------------------------------------------------------------------

# API で使用できない文字（サロゲート）の検出用
_SURROGATE_PATTERN = re.compile(r"[\uD800-\uDFFF]")


def _find_invalid_unicode(_label: str, s: str) -> list[tuple[int, str]]:
    """文字列中の不正な Unicode（サロゲート）の位置とコードを (位置, U+XXXX) のリストで返す。"""
    if not s:
        return []
    result: list[tuple[int, str]] = []
    for m in _SURROGATE_PATTERN.finditer(s):
        result.append((m.start(), f"U+{ord(m.group()):04X}"))
    return result


def validate_prompt_inputs(url: str, user_prompt: str) -> None:
    """
    記事作成プロンプトの入力（URL と自由プロンプト）に API で使用できない文字が含まれていないか検証する。
    含まれる場合は、入力名・位置・文字コードを示して ValueError を送出する。
    build_article_agent_prompt() に渡す前に main.py から呼ぶ想定。
    """
    url_s = (url or "").strip()
    prompt_s = (user_prompt or "").strip()

    errors: list[str] = []
    for label, text in [("対象URL", url_s), ("自由プロンプト", prompt_s)]:
        invalid = _find_invalid_unicode(label, text)
        if invalid:
            details = ", ".join(f"{pos + 1} 文字目: {code}" for pos, code in invalid[:5])
            if len(invalid) > 5:
                details += f" 他 {len(invalid) - 5} 箇所"
            errors.append(f"- {label}: {details}")

    if errors:
        raise ValueError(
            "入力に API で使用できない文字が含まれています（不正な Unicode）。\n"
            "コピー＆ペースト元の文字や入力のやり直しを試してください。\n"
            + "\n".join(errors)
        )


# -----------------------------------------------------------------------------
# 記事作成エージェント用（プロンプト本文・ツール説明）
# -----------------------------------------------------------------------------

# Claude に渡す「役割と手順」のシステム的な指示。build_article_agent_prompt() の先頭に連結される。
ARTICLE_AGENT_INSTRUCTION = """
あなたは社内向けの「記事作成エージェント」です。

【役割】
- 指定URLのWeb記事を読み、Confluence 貼り付け用の Markdown 記事を作成する。
- 完成前に、必ずレビューエージェントのフィードバックを得て品質を高める。

【必須の流れ】
1. Playwright MCP で対象URLの内容を取得する。
2. 要約・重要ポイント・参考リンク・次アクションを含む記事ドラフトを書く。
3. request_review ツールでレビューエージェントにドラフトを送り、フィードバックを得る。
4. フィードバックを踏まえて記事を修正する。必要なら 3 に戻り、再度 request_review を呼ぶ（回数はあなたの判断でよい。OK が出るか十分満足できるまで繰り返してよい）。
5. 最終版ができたら、完成した Markdown 本文のみを出力して終了する。

【記事の要件】
- 見出しと箇条書きを多用し、日本語で書く。
- 参考リンクには参照元URLを必ず含める。
- ユーザーから自由プロンプト（例：経営層向け／技術者向け／短め）があればそれに沿う。
"""

# request_review ツールの説明。Claude が「いつ・何回レビューを依頼するか」を判断するための文言。
REQUEST_REVIEW_TOOL_DESCRIPTION = (
    "レビューエージェント（A2A）に記事ドラフトを送り、改善点やフィードバックを得る。"
    "指摘を反映したら再度このツールを呼んでよい。何回呼ぶかはあなたの判断に任せる。"
)


def build_article_agent_prompt(url: str, user_prompt: str) -> str:
    """今回の対象 URL と自由プロンプトを ARTICLE_AGENT_INSTRUCTION に埋め込み、1 本のプロンプト文字列にする。"""
    url_s = (url or "").strip()
    user_part = (user_prompt or "").strip() or "(指定なし)"
    return f"""{ARTICLE_AGENT_INSTRUCTION}

【今回の依頼】
- 対象URL: {url_s}
- ユーザー要望（自由プロンプト）: {user_part}

上記の流れに従い、記事を作成し、レビューを繰り返してから最終版の Markdown 本文のみを出力してください。
"""


# -----------------------------------------------------------------------------
# レビューエージェント（A2A）用の設定・文言
# -----------------------------------------------------------------------------

# A2A の /.well-known/agent-card.json に載せるメタデータ
REVIEW_AGENT_NAME = "レビューエージェント"
REVIEW_AGENT_DESCRIPTION = "ドラフトをレビューしてチェックリストを返すA2Aエージェント。"
REVIEW_SKILL_ID = "review_draft"
REVIEW_SKILL_NAME = "レビュー（Confluenceドラフト）"
REVIEW_SKILL_DESCRIPTION = "Confluence向けドラフトの不足セクションと改善点をチェックします。"
REVIEW_SKILL_EXAMPLES = ["このドラフトをレビューして", "不足セクションを指摘して"]
REVIEW_AGENT_VERSION = "1.0.0"

# レビュー用 LLM への指示。観点に基づいてフィードバックを出すよう指定する。
REVIEW_AGENT_INSTRUCTION = """
あなたは社内向け Tech News まとめ記事の「レビュワー」です。
Confluence 貼り付け用 Markdown ドラフトを受け取り、以下の観点に基づいてレビューし、改善点を簡潔に返してください。

【レビュー観点】
1. 構成・網羅性: 要約・重要ポイント・参考リンク・次アクションの 4 セクションが揃っているか。論点が過不足なく網羅されているか。
2. 明確性: 結論やメッセージが明確か。専門用語に説明があるか。「何をすべきか」が読み手に伝わるか。
3. 正確性・根拠: 事実・数値・引用が正確か。一次ソースや参照元 URL が適切に含まれているか。
4. 実用性: 社内の「次アクション」や活用のヒントが具体的で、実務に落とし込めるか。
5. 読みやすさ: 見出し・箇条書き・段落が適切か。分量は目的に合っているか。
6. 対象読者: 想定読者（経営層／技術者／一般）に合ったトーン・詳細度・用語か。

【出力形式】
- 各観点について、良い点または改善点を 1〜2 文で述べる。改善点は箇条書きで具体的に。
- 最後に 1 行で総合所見（OK / 要修正の程度）を書く。
- 日本語で、記事作成者が修正しやすいように簡潔に書く。
"""

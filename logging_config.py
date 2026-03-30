"""
実行ログを log/ に出力するための共通設定。

- 記事作成エージェント: 1 回の実行ごとに article_agent_YYYYMMDD_HHMMSS.fff.log を新規作成（.fff はミリ秒）。
- レビューエージェント: 1 回の起動ごとに review_agent_YYYYMMDD_HHMMSS.fff.log を新規作成（.fff はミリ秒）。

両エージェントでファイル名・ログ形式を揃えるため、タイムスタンプ生成は get_log_timestamp() で統一する。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

# ログファイルを置くディレクトリ（プロジェクトルートからの相対パス）
LOG_DIR = "log"

# ログファイル名用タイムスタンプ形式（YYYYMMDD_HHMMSS.fff。記事・レビューで共通）
LOG_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S.%f"
LOG_TIMESTAMP_MICRO_TRIM = 3  # マイクロ秒の上3桁（ミリ秒）まで使う


def get_log_timestamp() -> str:
    """ログファイル名に使うタイムスタンプを返す（記事・レビュー共通）。例: 20260317_022427.593（.593 はミリ秒）"""
    s = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
    return s[: -(6 - LOG_TIMESTAMP_MICRO_TRIM)]  # マイクロ秒6桁のうち上3桁（ミリ秒）まで


def ensure_log_dir(log_dir: str = LOG_DIR) -> Path:
    """指定ディレクトリが無ければ作成し、その Path を返す。"""
    p = Path(log_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_file_handler(log_path: Path) -> logging.FileHandler:
    """UTF-8 で log_path に書き出す FileHandler。フォーマットは時刻・レベル・ロガー名・メッセージ。"""
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    handler.setLevel(logging.DEBUG)
    return handler


def setup_article_agent_log(run_id: str, log_dir: str = LOG_DIR) -> logging.Logger:
    """
    記事作成エージェント用ロガーを設定する。
    - ファイル名は {run_id}.log（例: article_agent_20260316_094500.123.log）。
    - 既存の FileHandler は削除してから新しいハンドラを追加する（複数実行してもハンドラが溜まらないようにする）。

    run_id: ログファイル名のベース（例: article_agent_20260316_094500.123）
    戻り値: 使用する Logger（名前は "article_agent"）
    """
    ensure_log_dir(log_dir)
    log_path = Path(log_dir) / f"{run_id}.log"

    logger = logging.getLogger("article_agent")
    logger.setLevel(logging.DEBUG)
    for h in logger.handlers[:]:
        if isinstance(h, logging.FileHandler):
            h.close()
            logger.removeHandler(h)
    handler = _make_file_handler(log_path)
    logger.addHandler(handler)
    logger.propagate = False  # root に伝播させず、このロガーだけで完結させる
    return logger


def setup_review_agent_log(run_id: str, log_dir: str = LOG_DIR) -> logging.Logger:
    """
    レビューエージェント用ロガーを設定する。
    - ファイル名は {run_id}.log（例: review_agent_20260316_112000.123.log）。
    - root ロガーに FileHandler を追加するため、uvicorn のアクセスログなども同じファイルに出力される。

    run_id: ログファイル名のベース（例: review_agent_20260316_112000.123）
    戻り値: アプリ用 Logger（名前は "review_agent"）
    """
    ensure_log_dir(log_dir)
    log_path = Path(log_dir) / f"{run_id}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = _make_file_handler(log_path)
    root.addHandler(handler)

    logger = logging.getLogger("review_agent")
    logger.setLevel(logging.DEBUG)
    return logger

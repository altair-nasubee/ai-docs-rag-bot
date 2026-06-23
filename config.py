"""設定の一元管理。

API キー・モデル名・各種パスをここから取得する。
ローカル実行では `.env`、本番（Streamlit Community Cloud）では `st.secrets`
の両方に対応する。優先順位は「環境変数 → st.secrets → 既定値」。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ローカル実行時のみ .env を読み込む（本番では存在しないため no-op）。
load_dotenv()


def _get(key: str, default: str | None = None) -> str | None:
    """環境変数 → st.secrets → 既定値 の順で設定値を取得する。

    st.secrets は Streamlit 実行時のみ利用可能で、未設定だと例外を投げるため
    遅延 import し、例外は握りつぶしてローカル実行を妨げないようにする。
    """
    value = os.getenv(key)
    if value:
        return value

    try:
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        # Streamlit 外での実行（ingest.py など）や secrets 未設定時はここに来る。
        pass

    return default


# ===== API キー =====
GROQ_API_KEY: str | None = _get("GROQ_API_KEY")
GOOGLE_API_KEY: str | None = _get("GOOGLE_API_KEY")

# ===== モデル設定 =====
GROQ_MODEL: str = _get("GROQ_MODEL", "llama-3.3-70b-versatile")
EMBED_MODEL: str = _get("EMBED_MODEL", "models/gemini-embedding-001")
EMBED_DIM: int = int(_get("EMBED_DIM", "768"))

# ===== 取得元 =====
# 公式ドキュメントのインデックス（.md リンク一覧）。
LLMS_TXT_URL: str = "https://code.claude.com/docs/llms.txt"

# ===== パス =====
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
CHROMA_DIR: Path = DATA_DIR / "chroma"          # ベクトルDBの永続化先
MANIFEST_PATH: Path = DATA_DIR / "manifest.json"  # 取り込み履歴・カテゴリ情報
QUIZ_PATH: Path = DATA_DIR / "quiz.json"          # 事前生成クイズ（フェーズ2）

# Chroma のコレクション名。
CHROMA_COLLECTION: str = "claude_code_docs"

# ===== RAG パラメータ =====
# Groq 無料枠 6,000 TPM に配慮し取得件数は控えめに。
RETRIEVAL_K: int = 4
# Gemini 埋め込み入力上限 2,048 トークンを超えないチャンク設定。
CHUNK_SIZE: int = 1000
CHUNK_OVERLAP: int = 120


def require(key: str) -> str:
    """必須キーを取得し、未設定なら分かりやすいエラーを投げる。"""
    value = _get(key)
    if not value:
        raise RuntimeError(
            f"環境変数 {key} が未設定です。.env または st.secrets に設定してください。"
        )
    return value

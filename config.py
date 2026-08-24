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
# 回答生成 LLM (Groq) のみ。埋め込みはローカル実行のためキー不要。
GROQ_API_KEY: str | None = _get("GROQ_API_KEY")

# ===== モデル設定 =====
# 既定は Groq がホストするオープンウェイトモデル。旧既定の
# llama-3.3-70b-versatile は Groq が 2026-08-16 に無料/開発者ティア向けを終了し、
# 404 (model_not_found) を返すため、公式が推奨する移行先へ変更した。
GROQ_MODEL: str = _get("GROQ_MODEL", "openai/gpt-oss-120b")
# gpt-oss 系は「推論（reasoning）モデル」で、最終回答の前に内部思考（reasoning）へ
# 出力トークンを消費する。小さすぎると思考で使い切って JSON が途中で切れ、大きすぎると
# gpt-oss-120b の無料枠 TPM(8000) に対し「prompt + max_tokens」が超過して 413
# （Request too large）になる。取り込み最大プロンプトのカテゴリ体系生成は
# ingest 側で説明文を短縮して prompt≒4074 トークンに圧縮済み（出力実測≒1459・
# 推論量のブレで前後する）。3072 なら 4074+3072=7146<8000 で 413 を避けつつ出力も
# 完結する。※ ドキュメント数が大幅に増えたら ingest 側の _DESC_LIMIT も見直す。
GROQ_MAX_TOKENS: int = int(_get("GROQ_MAX_TOKENS", "3072"))
# 推論の強さ。カテゴリ分類・クイズ生成のような定型 JSON 生成や RAG 回答では
# 最小限で十分（速く・トークン節約）。gpt-oss 系は low/medium/high、
# Qwen 系は none/default のみ対応。非対応モデルへ切替える場合はこの値を合わせる。
GROQ_REASONING_EFFORT: str = _get("GROQ_REASONING_EFFORT", "low")
# 埋め込みはローカル ONNX（fastembed）。多言語・クロスリンガル対応の小型モデル。
EMBED_MODEL: str = _get("EMBED_MODEL", "intfloat/multilingual-e5-small")
EMBED_DIM: int = int(_get("EMBED_DIM", "384"))
# e5 系は取り込み/検索でプレフィックスが必須。プレフィックス不要なモデル
# （例: paraphrase-multilingual-MiniLM-L12-v2）に切替える場合は両方を "" にする。
EMBED_QUERY_PREFIX: str = _get("EMBED_QUERY_PREFIX", "query: ")
EMBED_PASSAGE_PREFIX: str = _get("EMBED_PASSAGE_PREFIX", "passage: ")
# 埋め込みのバッチサイズ。大きいほど onnxruntime の活性化メモリが急増する
# （256で約4GB、8で約1.1GB）。低メモリ環境（Streamlit 1GB / 小型VM）でも
# OOM しないよう小さく保つ。
EMBED_BATCH_SIZE: int = int(_get("EMBED_BATCH_SIZE", "8"))

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
# 取得件数。広く短い質問（例:「Claude Code とは何か」）では関連ページが
# 上位に集まりにくいため、やや多めにして文脈を確保する（Groq 6,000 TPM 内）。
RETRIEVAL_K: int = 8
# 埋め込みモデルの最大系列長を超えないチャンク設定（文字数ベース）。
# e5-small は最大512トークン。1500文字 ≒ ~375トークンで上限内。
# ※ MiniLM(最大128トークン) に切替える場合は ~400 文字程度まで縮めること。
CHUNK_SIZE: int = 1500
CHUNK_OVERLAP: int = 200


def require(key: str) -> str:
    """必須キーを取得し、未設定なら分かりやすいエラーを投げる。"""
    value = _get(key)
    if not value:
        raise RuntimeError(
            f"環境変数 {key} が未設定です。.env または st.secrets に設定してください。"
        )
    return value

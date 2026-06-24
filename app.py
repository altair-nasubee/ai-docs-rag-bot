"""Streamlit 画面。

起動時に差分更新を1回だけ実行し、Claude Code 公式ドキュメントへの
日本語 Q&A を提供する。カテゴリ選択は任意（既定は全体から検索）。
"""

from __future__ import annotations

import streamlit as st

import config
import updater
from ingest import load_manifest
from rag import ALL_CATEGORIES, RagEngine

ALL_LABEL = "全体から検索（おすすめ）"

st.set_page_config(page_title="Claude Code ドキュメント Q&A", page_icon="💬")


@st.cache_resource(show_spinner="最新ドキュメントを確認中…")
def get_engine():
    """起動時に差分更新を1回だけ走らせ、RAG エンジンを返す（プロセス1回限り）。"""
    update_result = updater.update()
    engine = RagEngine()
    return engine, update_result


def _category_selectbox(engine: RagEngine) -> str:
    """メインエリア上部の任意カテゴリ選択。返り値は内部カテゴリ名。"""
    names = engine.category_names()
    labels = [ALL_LABEL] + names
    choice = st.selectbox("カテゴリ（任意・選ばなくてもOK）", labels, index=0)
    return ALL_CATEGORIES if choice == ALL_LABEL else choice


def _render_category_help(engine: RagEngine) -> None:
    with st.expander("各分野の説明と質問例"):
        for cat in engine.categories():
            st.markdown(f"**{cat['name']}** — {cat.get('description', '')}")
            for ex in cat.get("examples", []):
                if st.button(f"💡 {ex}", key=f"ex-{cat['name']}-{ex}"):
                    st.session_state["pending_question"] = ex
                    st.rerun()


def info_view(engine: RagEngine, update_result: dict) -> None:
    """補助情報（説明・ステータス・会話クリア）を表示するビュー。"""
    st.write(
        "Claude Code 公式ドキュメントを根拠に、日本語で質問へ回答します。"
        "カテゴリは選ばなくても全分野から検索します。"
    )
    manifest = load_manifest() or {}
    st.caption(f"使用モデル: {config.GROQ_MODEL}")
    st.caption(f"埋め込み: {config.EMBED_MODEL}")
    st.caption(f"基準DB構築: {manifest.get('built_at', '不明')}")
    st.caption(f"差分更新: {update_result.get('status', '不明')}")
    if st.button("会話をクリア"):
        st.session_state["messages"] = []
        st.rerun()


def _render_answer(result: dict) -> None:
    st.markdown(result["answer"])
    if result.get("used_categories"):
        st.caption("参照した分野: " + " / ".join(result["used_categories"]))
    if result.get("related_categories"):
        st.caption("関連しそうな分野: " + " / ".join(result["related_categories"]))
    sources = result.get("sources", [])
    if sources:
        with st.expander("出典"):
            for s in sources:
                st.markdown(f"- [{s['title']}]({s['url']})")


def qa_view(engine: RagEngine, prompt: str | None) -> None:
    category = _category_selectbox(engine)
    _render_category_help(engine)
    st.divider()

    messages = st.session_state.setdefault("messages", [])

    if not messages:
        st.info("カテゴリは選ばなくてOK。何が知りたいですか？上の質問例も使えます。")

    for msg in messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                _render_answer(msg["result"])
            else:
                st.markdown(msg["content"])

    # 画面下部に固定したチャット入力（main で取得）と、質問例ボタンからの投入を拾う。
    question = prompt or st.session_state.pop("pending_question", None)

    if question:
        messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("回答を生成中…"):
                try:
                    result = engine.answer(question, category=category)
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "answer": (
                            "回答の生成に失敗しました。無料枠のレート制限に達した可能性があります。"
                            f"\n\n（詳細: {exc}）"
                        ),
                        "sources": [],
                        "used_categories": [],
                        "related_categories": [],
                    }
            _render_answer(result)
        messages.append({"role": "assistant", "result": result})


def quiz_view() -> None:
    st.info("理解度クイズはフェーズ2で実装予定です。")


# セグメント切替の選択肢（簡潔なラベル）。
VIEW_QA = "💬 Q&A"
VIEW_QUIZ = "📝 クイズ"
VIEW_INFO = "ℹ️ 情報"


def main() -> None:
    st.title("💬 Claude Code ドキュメント Q&A")
    engine, update_result = get_engine()

    # メイン上部のセグメント切替でビューを選ぶ（タブの代わり）。
    view = (
        st.segmented_control(
            "表示切替",
            options=[VIEW_QA, VIEW_QUIZ, VIEW_INFO],
            default=VIEW_QA,
            label_visibility="collapsed",
        )
        or VIEW_QA  # 選択解除時は Q&A に戻す。
    )
    st.divider()

    if view == VIEW_QA:
        # st.chat_input はタブ/カラム等の外（トップレベル）で呼ぶと画面下部に固定される。
        prompt = st.chat_input("ここに質問を入力")
        qa_view(engine, prompt)
    elif view == VIEW_QUIZ:
        quiz_view()
    else:
        info_view(engine, update_result)


if __name__ == "__main__":
    main()

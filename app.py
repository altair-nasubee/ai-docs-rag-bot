"""Streamlit 画面。

起動時に差分更新を1回だけ実行し、Claude Code 公式ドキュメントへの
日本語 Q&A を提供する。カテゴリ選択は任意（既定は全体から検索）。
"""

from __future__ import annotations

import json
import random

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
        "Claude Code 公式ドキュメントをAIが検索し、チャットで質問とクイズができるアプリです。"
        "AIは無料でも使えるGroqを使用して、無料で運用しています。"
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


@st.cache_data(show_spinner=False)
def load_quiz() -> list[dict]:
    """事前生成したクイズ（data/quiz.json）を読み込む。"""
    if config.QUIZ_PATH.exists():
        data = json.loads(config.QUIZ_PATH.read_text(encoding="utf-8"))
        return data.get("questions", [])
    return []


def _reset_quiz() -> None:
    for k in ("quiz_questions", "quiz_idx", "quiz_score", "quiz_revealed", "quiz_choice"):
        st.session_state.pop(k, None)


def quiz_view() -> None:
    questions = load_quiz()
    if not questions:
        st.info("クイズは未生成です。`python gen_quiz.py` を実行すると出題できます。")
        return

    # --- 開始前: カテゴリ・出題数の設定 ---
    if "quiz_questions" not in st.session_state:
        cats = sorted({q["category"] for q in questions})
        choice = st.selectbox("分野", ["全分野"] + cats, index=0)
        pool = questions if choice == "全分野" else [q for q in questions if q["category"] == choice]
        st.caption(f"この分野の問題数: {len(pool)}")
        max_n = len(pool)
        num = st.slider("出題数", 1, max_n, min(5, max_n)) if max_n > 1 else max_n
        if st.button("スタート", type="primary"):
            st.session_state["quiz_questions"] = random.sample(pool, num)
            st.session_state["quiz_idx"] = 0
            st.session_state["quiz_score"] = 0
            st.session_state["quiz_revealed"] = False
            st.session_state["quiz_run"] = st.session_state.get("quiz_run", 0) + 1
            st.rerun()
        return

    qs = st.session_state["quiz_questions"]
    idx = st.session_state["quiz_idx"]
    total = len(qs)

    # --- 終了: 結果表示 ---
    if idx >= total:
        score = st.session_state["quiz_score"]
        st.subheader(f"スコア: {score} / {total} 正解")
        st.progress(score / total if total else 0.0)
        if st.button("もう一度", type="primary"):
            _reset_quiz()
            st.rerun()
        return

    # --- 出題 ---
    q = qs[idx]
    st.progress(idx / total, text=f"{idx + 1} / {total} 問")
    st.caption(f"分野: {q['category']}")
    st.markdown(f"**Q{idx + 1}. {q['question']}**")

    revealed = st.session_state["quiz_revealed"]
    selected = st.radio(
        "選択肢",
        options=range(4),
        format_func=lambda i: q["options"][i],
        index=None,
        key=f"quiz_radio_{st.session_state['quiz_run']}_{idx}",
        disabled=revealed,
        label_visibility="collapsed",
    )

    if not revealed:
        if st.button("回答する", type="primary", disabled=selected is None):
            st.session_state["quiz_choice"] = selected
            if selected == q["answer"]:
                st.session_state["quiz_score"] += 1
            st.session_state["quiz_revealed"] = True
            st.rerun()
        return

    # 採点結果＋解説（出題時に AI は呼ばない）。
    chosen = st.session_state.get("quiz_choice")
    if chosen == q["answer"]:
        st.success("✓ 正解")
    else:
        st.error(f"✗ 不正解 — 正解: {q['options'][q['answer']]}")
    if q.get("explanation"):
        st.info(f"解説: {q['explanation']}")

    last = idx == total - 1
    if st.button("結果を見る" if last else "次の問題へ", type="primary"):
        st.session_state["quiz_idx"] += 1
        st.session_state["quiz_revealed"] = False
        st.session_state.pop("quiz_choice", None)
        st.rerun()


# セグメント切替の選択肢（簡潔なラベル）。
VIEW_QA = "💬 Q&A"
VIEW_QUIZ = "📝 クイズ"
VIEW_INFO = "ℹ️ このアプリについて"


def main() -> None:
    st.header("💬 Claude Code Docs")
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

"""理解度クイズの事前一括生成（フェーズ2）。

取り込み済みの Chroma からカテゴリごとにチャンクを集め、Groq で4択クイズ
（問題 / 選択肢4つ / 正解 / 解説）を生成して `data/quiz.json` に保存する。
AI を呼ぶのはこの生成時のみ。出題時（app.py）は JSON を読むだけで AI を呼ばない。

CLI:
  python gen_quiz.py                 # 各カテゴリ4問
  python gen_quiz.py --per-category 3
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Dict, List

import config
from ingest import _chat_model, _extract_json, _get_chroma, load_manifest

SLEEP_SEC = 30  # Groq の TPM(6,000) に配慮した待機
MAX_CONTEXT_CHARS = 6000


def _category_context(col, category: str) -> str:
    """指定カテゴリのチャンクを集め、なるべく別ページから文脈を作る。"""
    got = col.get(where={"category": category}, include=["documents", "metadatas"], limit=40)
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    by_source: Dict[str, str] = {}
    for doc, meta in zip(docs, metas):
        src = meta.get("source", "")
        if src not in by_source:  # 各ページの先頭チャンクを代表に
            by_source[src] = doc

    blocks: List[str] = []
    total = 0
    for text in by_source.values():
        if total + len(text) > MAX_CONTEXT_CHARS:
            break
        blocks.append(text)
        total += len(text)
    return "\n\n".join(blocks)


def _generate_for_category(category: str, context: str, n: int) -> List[dict]:
    """1カテゴリ分のクイズを生成する（Groq・429 はリトライ）。"""
    prompt = (
        "あなたは Claude Code ドキュメントの理解度を測るクイズ作成者です。\n"
        f"以下の参考ドキュメント（カテゴリ「{category}」）の内容だけに基づき、"
        f"日本語の4択クイズを{n}問作成してください。\n"
        "ルール:\n"
        "- 各問題は参考ドキュメントの内容から答えられること。推測を要する問題は避ける。\n"
        "- 選択肢はちょうど4つ、正解は1つだけ。誤答は紛らわしいが明確に誤りと分かるものにする。\n"
        "- 各問題に1〜2文の日本語の解説を付ける。\n"
        '- answer は正解の選択肢の番号（0〜3）。\n\n'
        "出力は次の JSON のみ（前後に説明文を付けない）:\n"
        '{"questions":[{"question":"...","options":["A","B","C","D"],"answer":0,"explanation":"..."}]}\n\n'
        f"=== 参考ドキュメント ===\n{context}"
    )
    for attempt in range(4):
        try:
            resp = _chat_model().invoke(prompt)
            data = _extract_json(resp.content if hasattr(resp, "content") else str(resp))
            questions = data.get("questions", [])
            valid = []
            for q in questions:
                opts = q.get("options", [])
                ans = q.get("answer")
                if (
                    q.get("question")
                    and isinstance(opts, list)
                    and len(opts) == 4
                    and isinstance(ans, int)
                    and 0 <= ans <= 3
                ):
                    valid.append(
                        {
                            "category": category,
                            "question": q["question"].strip(),
                            "options": [str(o).strip() for o in opts],
                            "answer": ans,
                            "explanation": str(q.get("explanation", "")).strip(),
                        }
                    )
            return valid
        except Exception as exc:  # noqa: BLE001 — 429 等
            wait = 30 * (attempt + 1)
            print(f"      失敗({str(exc)[:50]})… {wait}s待機して再試行", flush=True)
            time.sleep(wait)
    return []


def build(per_category: int = 4) -> dict:
    manifest = load_manifest()
    if not manifest:
        raise RuntimeError("manifest がありません。先に ingest.py で基準DBを構築してください。")
    store = _get_chroma()
    col = store._collection

    categories = [c["name"] for c in manifest["categories"]]
    all_questions: List[dict] = []
    print(f"カテゴリ {len(categories)} 件 × {per_category}問 を生成します", flush=True)
    for i, cat in enumerate(categories, 1):
        context = _category_context(col, cat)
        if not context:
            print(f"[{i}/{len(categories)}] {cat}: 文脈なし・スキップ", flush=True)
            continue
        qs = _generate_for_category(cat, context, per_category)
        all_questions.extend(qs)
        print(f"[{i}/{len(categories)}] {cat}: {len(qs)}問", flush=True)
        if i < len(categories):
            time.sleep(SLEEP_SEC)

    quiz = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": config.GROQ_MODEL,
        "questions": all_questions,
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.QUIZ_PATH.write_text(
        json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完了: {len(all_questions)}問 を {config.QUIZ_PATH} に保存", flush=True)
    return quiz


def main() -> None:
    parser = argparse.ArgumentParser(description="クイズ事前生成")
    parser.add_argument("--per-category", type=int, default=4, help="カテゴリあたりの問題数")
    args = parser.parse_args()
    build(per_category=args.per_category)


if __name__ == "__main__":
    main()

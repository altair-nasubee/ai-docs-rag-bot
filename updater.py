"""起動時の差分更新。

`llms.txt` を取得して保存済み manifest と比較し、変更があったページだけを
再取り込みする。フルクロールはしない。AI 利用を最小化するため、新規ページの
カテゴリは LLM ではなくカテゴリ代表ベクトルとの類似度で割当てる。

検知できるのは llms.txt から分かる範囲（URL の追加・削除・1行説明の変化）まで。
本文のみの更新は llms.txt からは検知できないため、基準DBの再構築
（ローカル / GitHub Actions で `ingest.py` を再実行）でまとめて追従する。

レート制限・ネットワーク失敗時は更新をスキップし、既存DBで動作を継続する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Tuple

import ingest
from embedding import LocalEmbeddings
from ingest import Page


def _diff(
    current: List[Page], previous_pages: Dict[str, dict]
) -> Tuple[List[Page], List[str]]:
    """現在の llms.txt と manifest を比較し、(再取り込み対象, 削除URL) を返す。

    再取り込み対象 = 新規 URL ＋ 1行説明が変化した既存 URL。
    """
    current_urls = {p.url for p in current}
    to_ingest: List[Page] = []
    for page in current:
        prev = previous_pages.get(page.url)
        if prev is None or prev.get("description", "") != page.description:
            to_ingest.append(page)
    removed = [url for url in previous_pages if url not in current_urls]
    return to_ingest, removed


def update() -> dict:
    """差分更新を実行し、結果サマリを返す。失敗時は安全にスキップする。"""
    result = {"status": "skipped", "added": 0, "changed": 0, "removed": 0, "reason": ""}

    manifest = ingest.load_manifest()
    if not manifest:
        # 基準DBが無い場合は差分更新の対象外（ingest.py での初回構築が必要）。
        result["reason"] = "manifest が無いため差分更新をスキップ"
        return result

    try:
        current = ingest.fetch_llms_txt()
    except Exception as exc:  # noqa: BLE001 — ネットワーク失敗時は既存DBで継続。
        result["reason"] = f"llms.txt 取得失敗: {exc}"
        return result

    previous_pages: Dict[str, dict] = manifest.get("pages", {})
    to_ingest, removed = _diff(current, previous_pages)

    if not to_ingest and not removed:
        result["status"] = "no_change"
        return result

    try:
        store = ingest._get_chroma()
        embedder = LocalEmbeddings()
        category_vectors: Dict[str, List[float]] = manifest.get("category_vectors", {})

        added = changed = 0
        for page in to_ingest:
            ingest.fetch_page_content(page)
            chunks, vectors = ingest._embed_page(embedder, page)
            if not chunks:
                continue

            prev = previous_pages.get(page.url)
            if prev is None:
                # 新規ページ: LLM を呼ばず最近傍カテゴリへ自動割当て。
                page_vec = ingest._mean_vector(vectors)
                category = ingest.nearest_category(page_vec, category_vectors) or ""
                added += 1
            else:
                # 既存ページの説明変更: カテゴリは維持し本文だけ入れ替え。
                category = prev.get("category", "")
                changed += 1

            page.category = category
            for chunk in chunks:
                chunk.metadata["category"] = category
            ingest._store_chunks(store, chunks, vectors)

            previous_pages[page.url] = {
                "title": page.title,
                "description": page.description,
                "content_hash": page.content_hash,
                "category": category,
            }

        for url in removed:
            ingest._delete_urls_from_store(store, [url])
            previous_pages.pop(url, None)

        manifest["pages"] = previous_pages
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        ingest.save_manifest(manifest)

        result.update(
            status="updated", added=added, changed=changed, removed=len(removed)
        )
    except Exception as exc:  # noqa: BLE001 — レート制限等は既存DBで継続。
        result["reason"] = f"差分更新中にエラー（既存DBで継続）: {exc}"
        result["status"] = "error"

    return result


if __name__ == "__main__":
    print(update())

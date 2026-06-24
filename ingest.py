"""ドキュメント取り込み（初回構築・差分更新の共通処理）。

処理の流れ:
  1. `llms.txt` を取得し `.md` の URL・タイトル・説明を抽出
  2. 各 `.md` を取得し本文ハッシュを算出
  3. 取り込み時に一度だけ LLM でカテゴリ体系を生成し、各ページを割当て
  4. チャンク分割 → ローカル ONNX で埋め込み → Chroma に永続化
  5. `data/manifest.json` に URL・ハッシュ・カテゴリ・代表ベクトルを保存

CLI:
  python ingest.py            # 全ページを取り込み（初回構築）
  python ingest.py --limit 5  # 先頭5ページだけ取り込み（試験実行）
  python ingest.py --reset    # 既存 data/ を消してから取り込み
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from embedding import LocalEmbeddings, _l2_normalize

# llms.txt の各行: "- [タイトル](URL): 説明"
_LINE_RE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<url>https?://\S+?\.md)\)(?::\s*(?P<desc>.*))?$")


@dataclass
class Page:
    url: str
    title: str
    description: str
    content: str = ""
    content_hash: str = ""
    category: str = ""


# --------------------------------------------------------------------------
# 取得・パース
# --------------------------------------------------------------------------
def _http_get(url: str, retries: int = 4) -> requests.Response:
    """一時的なエラー（5xx・429・タイムアウト）はバックオフして再試行する。

    公式ドキュメントサーバーが稀に 502 等を返すため、1ページの一時障害で
    取り込み全体が落ちないようにする。
    """
    import time

    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code in (429, 500, 502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def fetch_llms_txt() -> List[Page]:
    """llms.txt を取得し、ページ一覧（本文未取得）を返す。"""
    resp = _http_get(config.LLMS_TXT_URL)
    return parse_llms_txt(resp.text)


def parse_llms_txt(text: str) -> List[Page]:
    """llms.txt 本文から `.md` ページ一覧を抽出する。"""
    pages: List[Page] = []
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        pages.append(
            Page(
                url=m.group("url"),
                title=m.group("title").strip(),
                description=(m.group("desc") or "").strip(),
            )
        )
    return pages


def fetch_page_content(page: Page) -> Page:
    """ページの `.md` を取得し、本文とハッシュを埋める（一時エラーは再試行）。"""
    resp = _http_get(page.url)
    page.content = resp.text
    page.content_hash = hashlib.sha256(resp.text.encode("utf-8")).hexdigest()
    return page


# --------------------------------------------------------------------------
# カテゴリ分類（取り込み時の LLM 利用はここだけ）
# --------------------------------------------------------------------------
def _chat_model() -> ChatGroq:
    return ChatGroq(
        model=config.GROQ_MODEL,
        api_key=config.require("GROQ_API_KEY"),
        temperature=0,
    )


def _extract_json(text: str) -> dict:
    """LLM 出力から最初の JSON オブジェクトを抽出してパースする。"""
    # ```json ... ``` のコードフェンスを除去。
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON を抽出できませんでした: {text[:200]}")
    return json.loads(raw[start : end + 1])


# 受け皿（catch-all）とみなすカテゴリ名（部分一致・小文字で判定）。
_CATCHALL_NAMES = ("その他", "ミスセル", "雑多", "other", "misc", "miscellaneous", "etc")


def _is_catchall(name: str) -> bool:
    low = name.strip().lower()
    return any(k in low for k in _CATCHALL_NAMES)


def generate_taxonomy(pages: List[Page]) -> List[dict]:
    """全ページのタイトル＋説明からカテゴリ体系を生成する（LLM 1回）。

    返り値: [{"name": str, "description": str, "examples": [str, ...]}, ...]
    """
    listing = "\n".join(f"- {p.title}: {p.description}" for p in pages)
    n_hint = max(3, min(12, round(len(pages) / 12) + 3))
    prompt = (
        "あなたは技術ドキュメントの情報設計の専門家です。"
        "以下は Claude Code 公式ドキュメントのページ一覧（英語タイトルと説明）です。\n"
        "これらを、初学者にも分かりやすい日本語のカテゴリへ分類する『カテゴリ体系』を作ってください。\n"
        f"カテゴリ数は内容に応じて {n_hint} 個程度にまとめること。\n"
        "重要: 「その他」「ミスセル」「Other」「Miscellaneous」のような漠然とした"
        "受け皿（catch-all）カテゴリは作らないこと。すべてのカテゴリは具体的で意味のある"
        "テーマにし、どのページも必ずいずれかの具体的なカテゴリに収まるようにすること。\n"
        "各カテゴリには、日本語のカテゴリ名・一文の説明・そのカテゴリで尋ねそうな日本語の質問例を2つ付けること。\n\n"
        "出力は次の JSON のみ（前後に説明文を付けない）:\n"
        '{"categories": [{"name": "日本語カテゴリ名", "description": "一文の説明", '
        '"examples": ["質問例1", "質問例2"]}]}\n\n'
        f"=== ページ一覧 ===\n{listing}"
    )
    resp = _chat_model().invoke(prompt)
    data = _extract_json(resp.content if hasattr(resp, "content") else str(resp))
    categories = data.get("categories", [])
    # 保険: 指示に反して catch-all（その他/Other 等）が生成されても除外する。
    categories = [c for c in categories if not _is_catchall(c.get("name", ""))]
    if not categories:
        raise ValueError("カテゴリ体系を生成できませんでした。")
    # examples が無い場合に備えて整形。
    for c in categories:
        c.setdefault("description", "")
        c.setdefault("examples", [])
    return categories


def assign_categories(
    pages: List[Page], category_names: List[str], batch_size: int = 40
) -> Dict[str, str]:
    """各ページを既定カテゴリのいずれかへ割当てる（バッチで LLM 呼び出し）。

    返り値: {url: category_name}
    """
    assignments: Dict[str, str] = {}
    names_block = "\n".join(f"- {n}" for n in category_names)
    for start in range(0, len(pages), batch_size):
        batch = pages[start : start + batch_size]
        listing = "\n".join(
            f"{i}. {p.title}: {p.description}" for i, p in enumerate(batch)
        )
        prompt = (
            "次のカテゴリ一覧のいずれかに、各ページを1つだけ割当ててください。\n"
            "カテゴリ名は一覧の表記と完全に一致させること。\n\n"
            f"=== カテゴリ一覧 ===\n{names_block}\n\n"
            f"=== ページ（番号付き）===\n{listing}\n\n"
            '出力は次の JSON のみ: {"assignments": {"0": "カテゴリ名", "1": "カテゴリ名"}}'
        )
        resp = _chat_model().invoke(prompt)
        data = _extract_json(resp.content if hasattr(resp, "content") else str(resp))
        mapping = data.get("assignments", {})
        for i, page in enumerate(batch):
            name = mapping.get(str(i)) or mapping.get(i)
            if name not in category_names:
                name = category_names[0]  # 不正な割当ては先頭カテゴリへフォールバック
            assignments[page.url] = name
    return assignments


# --------------------------------------------------------------------------
# 分割・埋め込み・保存
# --------------------------------------------------------------------------
def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )


def _build_chunks(pages: List[Page]) -> List[Document]:
    """ページ群をチャンク Document に分割する（メタデータ付き）。"""
    splitter = _splitter()
    docs: List[Document] = []
    for page in pages:
        for i, chunk in enumerate(splitter.split_text(page.content)):
            docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source": page.url,
                        "title": page.title,
                        "category": page.category,
                        "content_hash": page.content_hash,
                        "chunk": i,
                    },
                )
            )
    return docs


def _get_chroma():
    """Chroma ベクトルストアを取得（永続化・コサイン距離）。"""
    from langchain_chroma import Chroma

    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=config.CHROMA_COLLECTION,
        embedding_function=LocalEmbeddings(),
        persist_directory=str(config.CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def _delete_urls_from_store(store, urls: List[str]) -> None:
    """指定 URL のチャンクを Chroma から削除する（差分更新で再利用）。"""
    for url in urls:
        store.delete(where={"source": url})


def _page_up_to_date(store, page: Page) -> bool:
    """同一 URL・同一本文ハッシュのチャンクが既に Chroma にあるか判定する。

    取り込みが途中で止まっても、再実行時に完了済みページをスキップできる
    （無駄な再埋め込みを防ぐ）。
    """
    got = store._collection.get(where={"source": page.url}, include=["metadatas"])
    metas = got.get("metadatas") or []
    return bool(metas) and all(m.get("content_hash") == page.content_hash for m in metas)


def _embed_page(
    embedder: LocalEmbeddings, page: Page
) -> Tuple[List[Document], List[List[float]]]:
    """1ページを分割・埋め込みする（保存はしない）。チャンクとベクトルを返す。"""
    chunks = _build_chunks([page])
    if not chunks:
        return [], []
    vectors = embedder.embed_documents([d.page_content for d in chunks])
    return chunks, vectors


def _store_chunks(store, chunks: List[Document], vectors: List[List[float]]) -> None:
    """チャンクとベクトルを Chroma に保存する（同一 URL は入れ替え）。"""
    if not chunks:
        return
    ids = [f"{d.metadata['source']}#{d.metadata['chunk']}" for d in chunks]
    texts = [d.page_content for d in chunks]
    metadatas = [d.metadata for d in chunks]
    _delete_urls_from_store(store, list({d.metadata["source"] for d in chunks}))
    store._collection.add(
        ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas
    )


def _embed_and_store_page(store, embedder: LocalEmbeddings, page: Page) -> None:
    """1ページを分割・埋め込みして Chroma に保存する（ページ単位で永続化）。

    既存の同一 URL チャンクを削除してから入れ直すため、再取り込み・更新にも使える。
    """
    chunks, vectors = _embed_page(embedder, page)
    _store_chunks(store, chunks, vectors)


def nearest_category(
    vector: List[float], category_vectors: Dict[str, List[float]]
) -> Optional[str]:
    """ベクトルに最も近いカテゴリ名を返す（差分更新の新規ページ割当て用・LLM 不要）。"""
    best_name: Optional[str] = None
    best_score = -2.0
    for name, vec in category_vectors.items():
        if not vec:
            continue
        score = sum(x * y for x, y in zip(vector, vec))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _category_vectors_from_store(store) -> Dict[str, List[float]]:
    """保存済みチャンクの埋め込みをカテゴリ別に平均し、代表ベクトルを作る。"""
    got = store._collection.get(include=["embeddings", "metadatas"])
    embeddings = got.get("embeddings")
    embeddings = [] if embeddings is None else embeddings
    metadatas = got.get("metadatas") or []
    by_category: Dict[str, List[List[float]]] = {}
    for meta, emb in zip(metadatas, embeddings):
        by_category.setdefault(meta.get("category", ""), []).append(list(emb))
    return {name: _mean_vector(vecs) for name, vecs in by_category.items()}


def _mean_vector(vectors: List[List[float]]) -> List[float]:
    """ベクトル群の平均を L2 正規化して返す（カテゴリ代表ベクトル）。"""
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            acc[i] += v[i]
    mean = [a / len(vectors) for a in acc]
    return _l2_normalize(mean)


# --------------------------------------------------------------------------
# マニフェスト
# --------------------------------------------------------------------------
def load_manifest() -> Optional[dict]:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return None


def save_manifest(manifest: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# エントリポイント
# --------------------------------------------------------------------------
def build(limit: Optional[int] = None, reset: bool = False) -> dict:
    """初回構築。llms.txt から取り込んで DB と manifest を生成する。"""
    if reset and config.DATA_DIR.exists():
        shutil.rmtree(config.DATA_DIR)

    print("[1/5] llms.txt を取得中…")
    pages = fetch_llms_txt()
    if limit:
        pages = pages[:limit]
    print(f"      対象ページ数: {len(pages)}")

    print("[2/5] 各 .md を取得中…")
    fetched: List[Page] = []
    for i, page in enumerate(pages, 1):
        try:
            fetch_page_content(page)
            fetched.append(page)
            print(f"      ({i}/{len(pages)}) {page.url}")
        except Exception as exc:  # noqa: BLE001 — 取得失敗ページはスキップして続行。
            print(f"      ({i}/{len(pages)}) 取得失敗・スキップ: {page.url} ({exc})")
    pages = fetched
    if not pages:
        raise RuntimeError("取得できたページが1つもありません。")

    print("[3/5] カテゴリ体系を生成・割当て中（LLM）…")
    categories = generate_taxonomy(pages)
    category_names = [c["name"] for c in categories]
    assignments = assign_categories(pages, category_names)
    for page in pages:
        page.category = assignments[page.url]
    print(f"      カテゴリ: {', '.join(category_names)}")

    print("[4/5] 埋め込み・Chroma へ保存中…")
    store = _get_chroma()
    embedder = LocalEmbeddings()
    for i, page in enumerate(pages, 1):
        if _page_up_to_date(store, page):
            print(f"      ({i}/{len(pages)}) スキップ（更新なし）: {page.url}")
            continue
        _embed_and_store_page(store, embedder, page)
        print(f"      ({i}/{len(pages)}) 保存: {page.url}")

    print("[5/5] manifest.json を書き出し中…")
    category_vectors = _category_vectors_from_store(store)
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "embed_model": config.EMBED_MODEL,
        "embed_dim": config.EMBED_DIM,
        "groq_model": config.GROQ_MODEL,
        "pages": {
            p.url: {
                "title": p.title,
                "description": p.description,
                "content_hash": p.content_hash,
                "category": p.category,
            }
            for p in pages
        },
        "categories": categories,
        "category_vectors": category_vectors,
    }
    save_manifest(manifest)

    n_chunks = store._collection.count()
    print(f"完了: {len(pages)} ページ / {n_chunks} チャンク / {len(categories)} カテゴリ")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code ドキュメント取り込み")
    parser.add_argument("--limit", type=int, default=None, help="先頭 N ページのみ取り込み")
    parser.add_argument("--reset", action="store_true", help="既存 data/ を削除してから実行")
    args = parser.parse_args()
    build(limit=args.limit, reset=args.reset)


if __name__ == "__main__":
    main()

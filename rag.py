"""検索 + プロンプト + Groq 回答生成のチェーン。

利用時（質問のたび）に呼ばれる。質問を1回だけ埋め込み、その同じベクトルで
  - Chroma 検索（カテゴリ指定は任意）
  - 関連分野の推定（manifest のカテゴリ代表ベクトルとの類似度）
の両方をまかなうことで、追加の API コストを抑える。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_groq import ChatGroq

import config
from embedding import LocalEmbeddings
from ingest import _get_chroma, load_manifest

ALL_CATEGORIES = "全体から検索"

_llm_cache_enabled = False


def enable_llm_cache() -> None:
    """同一質問の Groq 呼び出しを SQLite キャッシュで再利用する（任意・冪等）。"""
    global _llm_cache_enabled
    if _llm_cache_enabled:
        return
    try:
        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache

        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        set_llm_cache(SQLiteCache(database_path=str(config.DATA_DIR / "llm_cache.db")))
        _llm_cache_enabled = True
    except Exception:
        # キャッシュは最適化に過ぎないため、失敗しても回答機能は継続する。
        pass

_ANSWER_PROMPT = """あなたは Claude Code 公式ドキュメントに詳しい日本語のアシスタントです。
以下の「参考ドキュメント」だけを根拠に、ユーザーの質問へ日本語で正確に答えてください。

ルール:
- 参考ドキュメントに書かれていないことは推測せず、「ドキュメントには記載がありません」と述べる。
- コードやコマンドは原文のまま示す。
- 簡潔に、必要なら箇条書きで。

=== 参考ドキュメント ===
{context}

=== 質問 ===
{question}

=== 回答（日本語）==="""


def _dot(a: List[float], b: List[float]) -> float:
    """内積。両者とも L2 正規化済みなのでコサイン類似度に一致する。"""
    return sum(x * y for x, y in zip(a, b))


class RagEngine:
    """Chroma 検索と Groq 回答生成をまとめたエンジン。"""

    def __init__(self) -> None:
        enable_llm_cache()
        self._store = _get_chroma()
        self._embedder = LocalEmbeddings()
        self._llm = ChatGroq(
            model=config.GROQ_MODEL,
            api_key=config.require("GROQ_API_KEY"),
            temperature=0,
        )
        manifest = load_manifest() or {}
        self._categories: List[dict] = manifest.get("categories", [])
        self._category_vectors: Dict[str, List[float]] = manifest.get(
            "category_vectors", {}
        )

    # ---- カテゴリ情報（UI 用）-------------------------------------------
    def category_names(self) -> List[str]:
        return [c["name"] for c in self._categories]

    def categories(self) -> List[dict]:
        """カテゴリ一覧（name/description/examples）を返す。"""
        return self._categories

    # ---- 関連分野の推定（案3）-----------------------------------------
    def related_categories(
        self, query_vector: List[float], top_n: int = 2
    ) -> List[str]:
        """質問ベクトルとカテゴリ代表ベクトルの類似度から関連分野を推定する。"""
        scored = [
            (name, _dot(query_vector, vec))
            for name, vec in self._category_vectors.items()
            if vec
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored[:top_n]]

    # ---- 検索 + 回答 ---------------------------------------------------
    def answer(self, question: str, category: Optional[str] = None) -> dict:
        """質問に回答する。

        返り値:
          {
            "answer": str,
            "sources": [{"title": str, "url": str}],
            "used_categories": [str],     # 参照した分野（案4）
            "related_categories": [str],  # 関連しそうな分野（案3）
          }
        """
        query_vector = self._embedder.embed_query(question)

        search_filter = None
        if category and category != ALL_CATEGORIES:
            search_filter = {"category": category}

        docs: List[Document] = self._store.similarity_search_by_vector(
            embedding=query_vector,
            k=config.RETRIEVAL_K,
            filter=search_filter,
        )

        context, sources, used_categories = self._format_context(docs)
        answer_text = self._llm.invoke(
            _ANSWER_PROMPT.format(context=context, question=question)
        ).content

        return {
            "answer": answer_text,
            "sources": sources,
            "used_categories": used_categories,
            "related_categories": self.related_categories(query_vector),
        }

    @staticmethod
    def _format_context(
        docs: List[Document],
    ) -> Tuple[str, List[dict], List[str]]:
        """取得文書を LLM 用コンテキスト・出典・参照カテゴリに整形する。"""
        blocks: List[str] = []
        sources: List[dict] = []
        seen_urls = set()
        used_categories: List[str] = []
        for doc in docs:
            title = doc.metadata.get("title", "")
            url = doc.metadata.get("source", "")
            category = doc.metadata.get("category", "")
            blocks.append(f"# {title}\n{doc.page_content}")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({"title": title, "url": url})
            if category and category not in used_categories:
                used_categories.append(category)
        return "\n\n".join(blocks), sources, used_categories

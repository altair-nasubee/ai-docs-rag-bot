"""ローカル ONNX 多言語埋め込みの共有ラッパー。

埋め込みを外部 API（旧 Gemini）ではなく、ローカルの ONNX モデル（fastembed）で
計算する。これにより API キー・クォータ・レート制限・コールドスタートのハングが
無くなり、Streamlit Community Cloud(1GB) / Hugging Face Spaces(16GB) のどちらでも
無料で動く。onnxruntime は chromadb の依存として既に同梱されている。

既定モデルは `intfloat/multilingual-e5-small`（384次元・多言語・クロスリンガル）。
e5 系は取り込み（文書）に `passage: `、検索（質問）に `query: ` のプレフィックスが
必須なので、ここで吸収する。プレフィックス・モデル名は config から差し替え可能で、
プレフィックス不要モデル（例: paraphrase-multilingual-MiniLM-L12-v2）にも対応する。
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings

import config

# fastembed の標準対応リストに無く、カスタム登録が必要なモデル。
_E5_SMALL = "intfloat/multilingual-e5-small"

# 同一モデルを複数回ロードしないための共有キャッシュ（メモリ二重消費を防ぐ）。
_MODEL_CACHE: Dict[str, TextEmbedding] = {}
_registered: set[str] = set()


def _l2_normalize(vector: List[float]) -> List[float]:
    """ベクトルを L2 正規化する（ゼロベクトルはそのまま返す）。"""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def _ensure_registered(model_name: str) -> None:
    """カスタム登録が要るモデル（e5-small）を一度だけ fastembed に登録する。"""
    if model_name != _E5_SMALL or model_name in _registered:
        return
    from fastembed.common.model_description import ModelSource, PoolingType

    TextEmbedding.add_custom_model(
        model=_E5_SMALL,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=_E5_SMALL),
        dim=config.EMBED_DIM,
        model_file="onnx/model.onnx",
    )
    _registered.add(model_name)


def _get_model(model_name: str) -> TextEmbedding:
    """モデルを取得（初回のみロード、以降はキャッシュ共有）。"""
    if model_name not in _MODEL_CACHE:
        _ensure_registered(model_name)
        _MODEL_CACHE[model_name] = TextEmbedding(model_name=model_name)
    return _MODEL_CACHE[model_name]


class LocalEmbeddings(Embeddings):
    """ローカル ONNX 埋め込み（プレフィックス付与＋L2正規化を内包）。

    - 文書取り込み: `passage: ` を付与
    - 質問検索:     `query: ` を付与
    プレフィックスは config で制御し、不要モデルでは空文字にする。
    """

    def __init__(self, progress: Optional[Callable[[int, int], None]] = None) -> None:
        self._model = _get_model(config.EMBED_MODEL)
        self._query_prefix = config.EMBED_QUERY_PREFIX
        self._passage_prefix = config.EMBED_PASSAGE_PREFIX
        # 取り込み進捗を表示するための任意コールバック (done, total)。
        self._progress = progress

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        prefixed = [self._passage_prefix + t for t in texts]
        # batch_size を小さく保ち onnxruntime の活性化メモリ急増（OOM）を防ぐ。
        vectors = [
            v.tolist()
            for v in self._model.embed(prefixed, batch_size=config.EMBED_BATCH_SIZE)
        ]
        out = [_l2_normalize(v) for v in vectors]
        if self._progress:
            self._progress(len(out), len(texts))
        return out

    def embed_query(self, text: str) -> List[float]:
        vector = list(self._model.embed([self._query_prefix + text]))[0]
        return _l2_normalize(vector.tolist())

---
title: Claude Code ドキュメント Q&A
emoji: 💬
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8501
pinned: false
tags:
  - streamlit
---

# ai-docs-rag-bot

Claude Code の公式ドキュメントを RAG で参照する、日本語 Q&A チャットボット。クイズ機能付き。

- **回答生成**: Groq `llama-3.3-70b-versatile`
- **埋め込み（検索）**: ローカル ONNX `intfloat/multilingual-e5-small`（fastembed・多言語・クロスリンガル・APIキー不要）
- **ベクトルDB**: Chroma（`data/` にリポジトリ同梱）

## セットアップ（ローカル）

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # GROQ_API_KEY を設定（埋め込みはローカルのためキー不要）
python ingest.py --reset   # 基準ベクトルDBを構築（data/ に保存）
streamlit run app.py
```

## デプロイ

公開先は **Hugging Face Spaces**（CPU Basic・16GB・無料）。Secrets に `GROQ_API_KEY` を設定し、`data/`（Chroma + manifest.json + quiz.json）をリポジトリに同梱する（`data/chroma` は Git LFS）。詳細手順は [`docs/DEPLOY.md`](docs/DEPLOY.md) を参照。

上部の YAML frontmatter は Hugging Face Spaces 用の設定です。

## ライセンスと帰属

- 本リポジトリの **MIT ライセンスは、本プロジェクト独自の実装コード**（`app.py` などのソース）に適用されます。
- 一方で `data/`（ベクトルDB・マニフェスト・クイズ）は **Claude Code 公式ドキュメント（© Anthropic）の内容に由来**します。ドキュメント本文の著作権は Anthropic に帰属し、MIT ライセンスはこの派生コンテンツを再ライセンスするものではありません。
- 回答には出典リンクを併記し、公式ドキュメントページを参照できるようにしています。

> このアプリは Claude Code 公式ドキュメントを学習・参照目的で RAG により利用する非公式プロジェクトです。

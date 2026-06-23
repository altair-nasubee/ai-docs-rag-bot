---
title: Claude Code ドキュメント Q&A
emoji: 💬
colorFrom: indigo
colorTo: blue
sdk: streamlit
sdk_version: 1.58.0
app_file: app.py
pinned: false
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

Streamlit Community Cloud（1GB）または Hugging Face Spaces（16GB・推奨）。
Secrets に `GROQ_API_KEY` を設定。`data/`（Chroma + manifest.json）はリポジトリに同梱する。

上部の YAML frontmatter は Hugging Face Spaces 用の設定（Streamlit Cloud では無視される）。

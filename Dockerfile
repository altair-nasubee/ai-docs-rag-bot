# Hugging Face Spaces 用 Dockerfile（Streamlit は Docker SDK 経由で動かす）。
# HF は Streamlit 単体 SDK を廃止したため、Docker テンプレートで起動する。
FROM python:3.11-slim

# 一部パッケージのビルドに必要な最小限のツール。
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces は非 root ユーザ（uid 1000）で実行される。書き込み可能な HOME を用意。
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# 依存を先に入れてレイヤキャッシュを効かせる。
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# アプリ一式（data/ の基準DBも含む）をコピー。
COPY --chown=user . .

# 埋め込みモデル(e5-small)をビルド時にダウンロード＆キャッシュしておく。
# これでコールドスタート時の実行時ダウンロードが無くなる（API キー不要）。
RUN python -c "import embedding; embedding.LocalEmbeddings()"

# Streamlit は 8501 固定（README frontmatter の app_port と一致させる）。
EXPOSE 8501
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]

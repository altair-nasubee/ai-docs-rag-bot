# CLAUDE.md

Claude Code の公式ドキュメント（英語・約150ページ）を、日本語で質問できる RAG チャットボット。
出典リンク付きで回答し、理解度クイズで復習できる。Streamlit 製・無料枠で動くことを前提に設計。

## ⛔ 最初に確認：Superpowers プラグイン（必須）

このプロジェクトは **Superpowers プラグイン**（`superpowers@claude-plugins-official`）が
インストールされている前提で開発する。**作業を始める前に、必ず導入状況を確認すること。**

- **確認方法**: Superpowers のスキル（`superpowers:brainstorming`、`superpowers:test-driven-development` など）が
  利用可能かどうかで判断する。利用できない場合は未インストール（または未有効化）とみなす。
- **未インストールの場合**: いきなり作業を始めず、**ユーザーに警告し、以下のインストールを促すこと。**

  ```
  ⚠️ このプロジェクトは Superpowers プラグインの利用を前提としていますが、現在インストールされていません。
     次のコマンドで導入してください（user スコープ推奨）:

       /plugin install superpowers@claude-plugins-official
       /reload-plugins
  ```

  - インストール後は `/reload-plugins`（またはセッション再起動）で有効化が必要。
  - **user スコープ**で入れると全プロジェクトで使える。`/plugin` 実行時に project を選ぶと
    このプロジェクト限定になるので注意。
- **インストール済みの場合**: そのまま Superpowers のワークフロー（brainstorm → plan → TDD → review）に従って進める。

## ライブラリのバージョン依存 API について（Context7）

LangChain / langchain-groq / langchain-chroma / Chroma など、バージョン更新で API や挙動が
変わりやすいライブラリを扱うときは、**Context7（`context7` MCP）で最新の公式ドキュメントを確認してから実装する**こと。
LLM の学習時点の古い・deprecated な API ではなく、最新ドキュメント由来の書き方をベースにする。

- Context7 は user スコープで登録済みの開発支援ツール（アプリ本体には組み込まない）。セットアップ手順は `docs/CONTEXT7.md` を参照。
- **使うと効く**: LangChain（import パス・Chain 系がよく変わる）、Pydantic v2 / SQLAlchemy 2.0 など破壊的変更の多いもの、新しめ・ニッチなライブラリ。
- **使わない**: 標準ライブラリ（`os` / `json` / `pathlib`）、`requests` / `numpy` の安定した基本機能、ライブラリと無関係なロジック・設計・リファクタリング。
- 判断基準は「有名かどうか」ではなく **「バージョン更新で破壊的変更が多いかどうか」**。

## 技術スタック

- **言語 / ランタイム**: Python 3.11
- **UI**: Streamlit（`:8501`）
- **LLM（回答生成）**: Groq（既定 `llama-3.3-70b-versatile`）。`GROQ_API_KEY` が必要。
- **埋め込み**: ローカル ONNX（fastembed / `intfloat/multilingual-e5-small`、384次元）。**API キー不要**。
- **ベクトルDB**: Chroma（`data/chroma` に永続化、コレクション名 `claude_code_docs`）
- **連携**: LangChain（`langchain` / `langchain-groq` / `langchain-chroma` / `langchain-text-splitters`）

## 主要ファイル

| ファイル | 役割 |
|--|--|
| `app.py` | Streamlit 画面。起動時に差分更新を1回実行し、日本語 Q&A を提供 |
| `rag.py` | 検索＋プロンプト＋Groq 回答生成チェーン（質問のたびに呼ばれる） |
| `ingest.py` | ドキュメント取り込み＆ Chroma 構築（`--reset` / `--limit N`） |
| `gen_quiz.py` | 4択クイズの事前一括生成 → `data/quiz.json`（生成時のみ AI 利用） |
| `updater.py` | 起動時の差分更新。`llms.txt` と manifest を比較し変更ページのみ再取込 |
| `embedding.py` | ローカル ONNX 埋め込みの共有ラッパー |
| `config.py` | 設定の一元管理。`環境変数 → st.secrets → 既定値` の順で解決 |

## よく使うコマンド

```bash
# アプリ起動（ローカル）
.venv/bin/streamlit run app.py            # http://localhost:8501

# ドキュメント取り込み（初回 / 作り直し）
.venv/bin/python ingest.py --reset
.venv/bin/python ingest.py --limit 10     # 先頭10ページだけ（動作確認用）

# クイズ生成
.venv/bin/python gen_quiz.py
```

> Python は `.venv/` の仮想環境を使う（例: `.venv/bin/python`）。

## 設定（config.py）

- 設定の優先順位は **環境変数 → `st.secrets` → 既定値**。ローカルは `.env`、本番（HF Spaces）は Secrets。
- 必須キーは `GROQ_API_KEY` のみ（埋め込みはローカルなのでキー不要）。
- データの実体は `data/`（`data/chroma` は **Git LFS**、`manifest.json` / `quiz.json` は通常 git）。

## ⚠️ 重要な落とし穴・設計上の制約

- **`EMBED_BATCH_SIZE`（既定8）を安易に上げない。** onnxruntime の活性化メモリが急増する（256で約4GB、8で約1.1GB）。低メモリ環境（Streamlit 1GB / 小型VM）では OOM するため小さく保つ。
- **e5 系はプレフィックス必須。** 取り込みは `passage: `、検索は `query: `（`EMBED_PASSAGE_PREFIX` / `EMBED_QUERY_PREFIX`）。プレフィックス不要なモデルに替えるときは両方 `""` にする。
- **`CHUNK_SIZE`（既定1500文字）はモデルの最大系列長に依存。** e5-small は最大512トークン（1500文字 ≒ ~375トークンで上限内）。MiniLM（最大128トークン）に替えるなら ~400文字まで縮める。
- **AI 呼び出しは最小化する設計。** クイズは事前生成（出題時は JSON を読むだけ）、差分更新の新規ページ分類も LLM ではなくカテゴリ代表ベクトルとの類似度で行う。質問時は埋め込みを1回だけ計算し、検索と分野推定の両方に使い回す。
- **無料枠が大前提。** Groq のレート制限（6,000 TPM）内に収める。`RETRIEVAL_K=8`。

## デプロイ

- 本番は **Hugging Face Spaces（無料・CPU Basic・16GB RAM）**、Docker SDK（`app_port: 8501`）。
- 手順は `docs/DEPLOY.md` を参照。

## テスト / 検証

- 現状、自動テスト（`tests/` 等）は無し。
- 変更後の動作確認は、アプリを起動して実際に「質問→回答→出典表示」「クイズ」が動くかをブラウザで確認する。**Playwright MCP**（`docs/PLAYWRIGHT.md`）で自動操作・スクショ撮影ができる。

### Playwright MCP を使うときの注意（開発時の動作確認用）

- **MCP は user スコープで登録済み**（`@playwright/mcp@latest --browser chromium`）。アプリ本体には組み込まない開発支援ツール。詳細・再セットアップは `docs/PLAYWRIGHT.md`。
- **必ず先にアプリを起動しておく。** Playwright で開く前に別ターミナルで `.venv/bin/streamlit run app.py` を立ち上げ、`http://localhost:8501` を対象にする（未起動だと接続エラー）。
- **WSL 環境はヘッドレス前提。** `--browser chromium` 指定が必須（外すと Chrome 本体を探して `Chromium distribution 'chrome' is not found` で失敗する）。ブラウザ依存が足りないときは `npx playwright install-deps`。
- MCP 設定の変更は稼働中の Claude Code には反映されないため、登録し直したら**再起動**する。

# Playwright (MCP) セットアップ手順（ステップバイステップ）

Claude Code に **Playwright MCP** を追加して、**実際のブラウザを操作**できるようにする手順です。
このプロジェクトの **Streamlit アプリ（`app.py` / ローカル `:8501`）** を自動で開いて、
「質問→回答」「クイズ」などの**動作確認やスクリーンショット撮影**に使えます。

> **Playwright MCP とは**
> Microsoft 製のブラウザ自動操作フレームワーク Playwright の MCP 版。
> Claude Code が Chromium などのブラウザを操作（ページを開く／クリック／入力／スクショ撮影）し、
> **アクセシビリティツリー（ページの構造）を読み取って画面の状態を把握**できる**開発支援ツール**です。

> **Context7 との違い**
> - Context7 = 最新ドキュメントを**読む**（書くときに効く）
> - Playwright = ブラウザを**操作する**（書いた後の動作確認・キャプチャに効く）
>
> アプリ本体には組み込みません。あくまで**開発時の Claude Code 用ツール**です。

---

## 0. 前提

- Claude Code CLI が使えること（`claude --version` で確認）。
- **Node.js / npx** が使えること（`node -v` / `npx -v` で確認）。Playwright MCP は npx で起動するため必須。
- **API キーやアカウントは不要**（Context7 と違いローカルで動く）。

---

## 1. Claude Code に MCP として登録する（user スコープ）

Playwright はどのプロジェクトでも使える**汎用ツール**なので、**`--scope user`（全プロジェクト横断）** で入れて使い回します。

```bash
claude mcp add --scope user playwright npx @playwright/mcp@latest
```

> 初回呼び出し時に npx がパッケージを取得するため、最初の起動は少し時間がかかることがあります。
>
> **スコープの違い（参考）**
> | スコープ | 適用範囲 | 共有 |
> |--|--|--|
> | `local`（既定） | このプロジェクトで自分だけ | されない |
> | `project` | リポジトリの全員（`.mcp.json` をコミット） | される |
> | **`user`（今回これ）** | **自分の全プロジェクト横断** | されない |

---

## 2. ブラウザ本体をインストールする

Playwright は操作対象のブラウザを別途ダウンロードします（初回のみ）。

```bash
npx playwright install chromium
```

> Chromium だけで十分です。全ブラウザが必要なら `npx playwright install`。
> Linux で依存ライブラリが不足する場合は `npx playwright install-deps` も実行。

---

## 3. 登録を確認する

```bash
claude mcp list
```

`playwright` が一覧に表示され、接続状態が正常（connected / ✓）であれば成功です。
Claude Code を起動中の場合は再起動して MCP を読み込み直してください。

---

## 4. このアプリで使ってみる

### 4-1. アプリをローカルで起動しておく

別ターミナルで Streamlit アプリを立ち上げておきます。

```bash
streamlit run app.py
# → http://localhost:8501 で起動
```

### 4-2. Claude Code に動作確認を依頼する

起動中の URL を伝えて、ブラウザ操作を頼みます。

```
http://localhost:8501 を Playwright で開いて、
「サブエージェントとは？」と質問を入力 → 回答が表示されることを確認して、
画面のスクリーンショットを撮って。
```

```
クイズ画面に切り替えて、選択肢をクリックし、
正誤判定が表示されるところまで動作確認して。
```

### 4-3. スクリーンショットの撮り直し（任意）

README 用キャプチャ（`docs/screenshots/ai-docs-rag-bot_1.png` / `_2.png`）を更新したいとき、
Playwright で同じ画面を開いて撮影 → 差し替え、という運用ができます。

---

## 主な使用場面

| 使う場面 | 例 |
|--|--|
| **動作確認（E2E）** | 「質問→回答→出典リンク表示」を実際にブラウザでなぞる |
| **UI のデグレ確認** | 変更後に画面が壊れていないか、要素が出ているか |
| **スクリーンショット撮影** | README 用キャプチャの自動取得・更新 |
| **動的ページの情報取得** | JS 描画されるページからの情報抽出 |

---

## トラブルシューティング

- **`claude mcp list` に出ない** → コマンドのスコープ/引数を確認し、Claude Code を再起動。
- **ブラウザ起動でエラー** → 手順 2 の `npx playwright install chromium`（必要なら `install-deps`）を実行。
- **`npx` が見つからない** → Node.js を導入（`node -v` で確認）。
- **WSL でブラウザが動かない** → ヘッドレス前提だが、依存不足は `npx playwright install-deps` で解消することが多い。
- **登録を変更/削除したい** → `claude mcp remove --scope user playwright` で削除し、手順 1 を再実行。

---

## 参考リンク

- Playwright MCP（GitHub）: <https://github.com/microsoft/playwright-mcp>
- Playwright 公式: <https://playwright.dev>

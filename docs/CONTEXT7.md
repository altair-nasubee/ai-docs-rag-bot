# Context7 セットアップ手順（ステップバイステップ）

Claude Code に **Context7 MCP** を追加して、LangChain など**バージョン更新で API が変わりやすいライブラリ**の
**最新の公式ドキュメント**を、コード生成の直前に参照できるようにする手順です。

> **Context7 とは**
> ライブラリの最新・バージョン対応のドキュメントとコード例を LLM のコンテキストに注入する MCP サーバー（Upstash 製）。
> LLM が学習時点の古い API で書いてしまうのを、最新ドキュメントで上書きするための**開発支援ツール**です。
> このプロジェクトでは **LangChain / langchain-groq / langchain-chroma** など更新の速い依存があるため、
> それらを改修するときに効果が出ます。

> **このプロジェクトでの位置づけ**
> アプリ本体（RAG ボット）には組み込みません。あくまで**開発時の Claude Code 用ツール**です。
> 常駐させてもデメリットはほぼなく、使う場面でだけ呼ばれます。

---

## 0. 前提

- Claude Code CLI が使えること（`claude --version` で確認）。
- ネットワーク接続（リモートの MCP サーバーに接続するため）。
- **Upstash アカウントは不要。** Context7 専用の無料アカウントだけで完結します。

---

## 1. 無料 API キーを取得する（推奨）

API キーなしでも動きますが、**匿名アクセスは全ユーザー共有で 60 リクエスト/時**しかなく、
すぐ `429 Too Many Requests` に当たります。**自分専用クォータ**になる無料キーを取っておくのが現実的です。

1. <https://context7.com/dashboard> にアクセスし、サインアップ（無料）。
2. ダッシュボードで **API キーを発行**する。
3. 表示された `ctx7sk-...` で始まるキーを控える（= 以降の `<CTX7_API_KEY>`）。

> Upstash 製ですが、別途 Upstash への登録は不要です。

---

## 2. Claude Code に MCP として登録する（user スコープ）

Context7 は LangChain でも Next.js でも使える**汎用ツール**なので、
特定プロジェクト限定ではなく **`--scope user`（全プロジェクト横断）** で一度入れて使い回します。

```bash
claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp \
  --header "CONTEXT7_API_KEY: <CTX7_API_KEY>"
```

> `<CTX7_API_KEY>` は手順 1 で取得した `ctx7sk-...` の値に置き換える。
>
> **スコープの違い（参考）**
> | スコープ | 適用範囲 | 共有 |
> |--|--|--|
> | `local`（既定） | このプロジェクトで自分だけ | されない |
> | `project` | リポジトリの全員（`.mcp.json` をコミット） | される |
> | **`user`（今回これ）** | **自分の全プロジェクト横断** | されない |

> ⚠️ キーは `~/.claude.json`（user 設定）に保存されます。**このファイルは外部に出さない**こと。

---

## 3. 登録を確認する

```bash
claude mcp list
```

`context7` が一覧に表示され、接続状態が正常（connected / ✓）であれば成功です。
Claude Code を起動中の場合は、再起動して MCP を読み込み直してください。

---

## 4. CLAUDE.md に利用ルールを書いておく（任意・推奨）

毎回プロンプトで指示しなくても、該当ライブラリを触るときに自動で参照させるため、
プロジェクトの `CLAUDE.md` に一文追加しておくと運用が安定します。

```md
## ライブラリのバージョン依存 API について
LangChain / langchain-groq / langchain-chroma / Chroma など、バージョン更新で API や挙動が変わりやすい
ライブラリを扱うときは、Context7（context7）で最新の公式ドキュメントを確認してから実装すること。
```

---

## 5. 使ってみる

実装を依頼するときに、変化の速いライブラリを触ると分かっている場合はプロンプトで促します。

```
LangChain の最新の Retrieval 周りの書き方を context7 で確認しながら rag.py を改修して。
```

deprecated な API ではなく、最新ドキュメント由来の正しい書き方をベースに実装してくれます。

---

## 補足：いつ使う / 使わない

| 使うと効く | あまり効かない |
|--|--|
| **LangChain**（import パス・Chain 系がよく変わる） | 標準ライブラリ（`os` / `json` / `pathlib`） |
| Pydantic v2 / SQLAlchemy 2.0 など破壊的変更のあるもの | `requests` / `numpy` の安定した基本機能 |
| 新しめ・ニッチで LLM の知識が薄いライブラリ | ライブラリと無関係なロジック・設計・リファクタリング |

> 判断基準は「有名かどうか」ではなく **「バージョン更新で破壊的変更が多いかどうか」**。

---

## トラブルシューティング

- **`claude mcp list` に出ない** → コマンドのスコープ/引数を確認し、Claude Code を再起動。
- **`429 Too Many Requests` / quota exceeded** → 匿名アクセスの共有上限。手順 1 の無料 API キーを登録する。
- **キーを変更/削除したい** → `claude mcp remove --scope user context7` で削除し、手順 2 を再実行。

---

## 参考リンク

- Context7（GitHub）: <https://github.com/upstash/context7>
- ダッシュボード（API キー発行）: <https://context7.com/dashboard>

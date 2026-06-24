# Hugging Face Spaces デプロイ手順（ステップバイステップ）

このアプリを **Hugging Face Spaces（無料・CPU Basic・16GB RAM）** に公開する手順です。
コマンドはこのリポジトリの実構成（Streamlit／Git LFS／`GROQ_API_KEY` のみ）に合わせています。

> 置き換え用プレースホルダ:
> - `<HF_USER>` … あなたの Hugging Face ユーザー名
> - `<SPACE_NAME>` … 作成する Space 名（例: `claude-code-qa`）
> - `<HF_TOKEN>` … Hugging Face の **write 権限**アクセストークン

---

## 0. 前提（このリポジトリで対応済みの項目）

デプロイに必要な準備は概ね完了しています。

- [x] `README.md` の先頭に HF Spaces 用 YAML frontmatter（**`sdk: docker` / `app_port: 8501`**。HF は Streamlit 単体SDKを廃止したため Docker 経由で起動）
- [x] `Dockerfile`（依存インストール＋8501で `streamlit run app.py`。埋め込みモデルをビルド時に事前キャッシュ）／`.dockerignore`
- [x] `requirements.txt`（Dockerfile がインストール）
- [x] 基準データ `data/`（`data/chroma` は **Git LFS**、`manifest.json` / `quiz.json` は通常 git）が**コミット済み**
- [x] `.gitattributes`（`data/chroma/** filter=lfs …`）
- [x] `.gitignore` で `.env` / `secrets.toml` / `data/llm_cache.db` を除外
- [x] git-lfs 導入済み

必要なのは「① HF アカウント＆トークン → ② Space 作成 → ③ push → ④ Secret 設定 → ⑤ 起動確認」だけです。

---

## 1. Hugging Face アカウントとアクセストークンを用意

1. <https://huggingface.co/join> でアカウント作成（無料）。
2. <https://huggingface.co/settings/tokens> → **New token**。
   - Name: 任意（例 `spaces-deploy`）
   - Token type: **Write**（必須）を選択すると細かいPermissionsを設定せずに書き込みで設定できる。
3. 表示された `hf_...` のトークンを控える（= `<HF_TOKEN>`）。push 時のパスワードに使います。

---

## 2. Space を作成する

1. <https://huggingface.co/new-space> を開く。
2. 設定:
   - **Owner**: 自分のアカウント
   - **Space name**: `<SPACE_NAME>`（例 `ai-docs-rag-bot`）
   - **License**: 任意（例 mit）
   - **Select the Space SDK**: **Docker** を選び、表示される一覧から **Streamlit** テンプレートを選ぶ
     （HF は Streamlit 単体SDKを廃止。Docker→Streamlit が現在の正式手順。本リポジトリは `Dockerfile` と `sdk: docker` 済みなので、push 時に上書きされる）
   - **Space hardware**: **CPU basic · 2 vCPU · 16 GB · FREE**
   - **Storage Bucket**: **Mount a bucket to this Space** は OFF のまま
   - **Visibility**: Public（無料）
3. **Create Space** を押す。空の Space（git リポジトリ）ができます。
   - Space の URL: `https://huggingface.co/spaces/<HF_USER>/<SPACE_NAME>`

---

## 3. ローカルの確認（任意・push 前チェック）

```bash
cd /home/defaultuser/work/ai-docs-rag-bot

# LFS 管理になっているか（data/chroma 配下が並べば OK）
git lfs ls-files

# コミット漏れがないか（data/ がコミット済みであること）
git status --short
```

> `data/chroma` が LFS 一覧に出ない場合は、先に
> `git lfs install && git lfs track "data/chroma/**" && git add .gitattributes data/chroma && git commit -m "track chroma via LFS"` を実施。

---

## 4. Space を git リモートに追加して push

HF Spaces は**それ自体が git リポジトリ**です。GitHub の `origin` とは別に、HF を `space` リモートとして追加し、そこへ push します（**LFS の実体も HF 側へアップロードされます**）。

```bash
cd /home/defaultuser/work/ai-docs-rag-bot

# HF Space をリモート追加（既にあれば set-url で上書き）
git remote add space https://huggingface.co/spaces/<HF_USER>/<SPACE_NAME>

# push（main ブランチ）
git push space main
```

- 認証を聞かれたら **Username = `<HF_USER>` / Password = `<HF_TOKEN>`**（write トークン）。
- 初回は LFS で `data/chroma`（約54MB）がアップロードされるため少し時間がかかります。
- push 後、HF 側で自動的にビルドが始まります。

> 毎回トークン入力を避けたい場合は、リモートURLに埋め込む方法もあります（取り扱い注意）:
> `git remote set-url space https://<HF_USER>:<HF_TOKEN>@huggingface.co/spaces/<HF_USER>/<SPACE_NAME>`

---

## 5. Secret（API キー）を設定する

埋め込みはローカル ONNX なのでキー不要。**必要なのは Groq のキーだけ**です。

1. Space ページ → **Settings** タブ。
2. **Variables and secrets** → **New secret**。
   - **Name**: `GROQ_API_KEY`
   - **Value**: あなたの Groq API キー（`gsk_...`）
   - 種別は **Secret**（Variable ではなく）にする。
3. 保存すると Space が自動で再起動（リビルド）します。

> HF の Secret は環境変数として渡されるため、`config.py` の `os.getenv("GROQ_API_KEY")` でそのまま読めます（コード変更不要）。

---

## 6. ビルド＆起動を確認

1. Space ページ右上のステータスが **Building → Running** になるのを待つ。
2. **初回ビルドは数分**かかります（Docker イメージのビルド＝依存インストール＋埋め込みモデルの事前ダウンロード）。うまくいかない時は **Logs** タブでエラーを確認。
3. モデルはイメージに焼き込まれるため、**2回目以降のコールドスタート（スリープ復帰）は実行時ダウンロードが無く高速**。
4. アプリが表示されたら、Q&A で「Claude Code とは何か」などを質問して回答・出典が出ることを確認。

---

## 7. スマホ実機で確認

- Space の公開URL（`https://huggingface.co/spaces/<HF_USER>/<SPACE_NAME>`）をスマホのブラウザで開く。
- 確認ポイント:
  - 下部固定のチャット入力で質問できる
  - 出典リンクが日本語ページ（`/docs/ja/...`）に飛ぶ
  - 「📝 クイズ」で出題・採点できる
  - タイトルや回答の折り返し・操作性

---

## 8. 更新したいとき

### コードや UI を直したら
```bash
git add -A
git commit -m "update"
git push space main      # （必要なら git push origin main も）
```
push すると HF が自動で再ビルドします。

### ドキュメントの内容を最新化したいとき（基準DB再構築）
揮発性FSのため、鮮度維持は**基準DBの作り直し＋コミット**で行います。
```bash
python ingest.py --reset     # 150ページを再取り込み（ローカル・無料）
python gen_quiz.py           # クイズも作り直す（任意）
git add data/                # chroma は LFS で更新される
git commit -m "rebuild base DB"
git push space main
```
（任意）GitHub Actions で `ingest.py` を定期実行して `data/` を再コミットすれば自動化できます。

---

## 9. トラブルシューティング

| 症状 | 原因・対処 |
| --- | --- |
| `GROQ_API_KEY が未設定です` エラー | STEP 5 の Secret 未設定。`GROQ_API_KEY` を Secret として登録し再起動。 |
| 検索結果が空 / DB が読めない | `data/chroma` が LFS ポインタのまま。`git lfs ls-files` で確認し、`git push space main` で LFS 実体が上がっているか確認。 |
| ビルドが失敗（依存関係） | `requirements.txt` / `Dockerfile` を確認。HF の Logs でどのステップ・パッケージで落ちたか確認。 |
| 初回ビルドが遅い（数分） | Docker イメージのビルド（依存＋モデル事前DL）のため正常。 |
| 8501 以外で待ち受け等のポートエラー | `Dockerfile` の `--server.port=8501` と README の `app_port: 8501` が一致しているか確認（HF は 8501 固定）。 |
| メモリ不足 | 16GB なので通常起きない。起きたら `EMBED_BATCH_SIZE` を下げる／軽量モデル（`paraphrase-multilingual-MiniLM-L12-v2`）へ `EMBED_MODEL` 切替。 |

---

## 付録: GitHub と連携させる別方式（参考）

`origin`（GitHub）を主にしたい場合、HF の「GitHub Actions で Space に同期」する方法もありますが、**GitHub の LFS と HF の LFS は別サーバ**のため設定がやや複雑です。本プロジェクトのように LFS を使う場合は、**本手順（HF へ直接 push）が最もシンプル**です。GitHub は `origin`、HF は `space` として両方に push すれば、ソース管理（GitHub）と公開（HF）を両立できます。

---

## チェックリスト（最終確認）

- [ ] HF アカウント＆ **write トークン**を取得した
- [ ] **Docker（Streamlit テンプレート）/ CPU Basic** の Space を作成した
- [ ] `git push space main` 成功（LFS 実体もアップロード）
- [ ] **`GROQ_API_KEY`** を Secret に登録した
- [ ] ステータスが **Running**・Q&A が回答する
- [ ] スマホ実機で表示・操作・出典リンクを確認した

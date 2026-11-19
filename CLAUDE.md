# bigboss-special-page

このリポジトリには複数の特集ページがある。

| 呼び名 | 場所 | 内容 |
|---|---|---|
| ボジョレー特集 | `index.html`（ルート） | ボジョレー・ヌーヴォー 2026 特集 |
| **ドリクラお歳暮特集** | `dreamcraft-oseibo-2026/index.html` | ドリームクラフト＆ビッグボス お歳暮特集 2026（黒・金・赤） |

ユーザーが「ドリクラお歳暮特集」「ドリクラのお歳暮」と言ったら `dreamcraft-oseibo-2026/` を修正する。

## ドリクラお歳暮特集の構成メモ

- 店舗：ドリームクラフト楽天市場店（`d-craft` / 店舗ID 296346）
- 商品データはページ下部の `<script>` 内の配列で管理（カードは JS で描画）
  - `products`：ビールギフト（サントリー・アサヒ・キリン・サッポロ）34点
  - `originals`：ドリームクラフトのオリジナルギフト
  - `hams`：ハムギフト 9点
  - 各要素の `price`（税込・数値）、`rid`（楽天商品番号）、`id`（品番）
- **価格変更時の注意**：「Pick Up」セクション（`#pickup`）の6セットは HTML に価格が直書き（`<p class="price">2,966<small>…`）。
  配列の `price` を変えたら、同じ商品が Pick Up にあればそちらも必ず直す。
- 価格の「〇年〇月〇日時点」表記はページ・README ともに削除済み（2026-11 のユーザー指示）。日付は入れない。
- 画像は `dreamcraft-oseibo-2026/img/` を参照（未アップロードのものは表示されない）。

## 店舗PCの自動化環境（2026-11 に新PCへ移行）

このリポジトリ外の、店舗PCで動く自動化（ロジ発注・クロスモール在庫アップロード・低在庫予約・入荷予定カレンダー・
auメルマガ・rakuten_yoru・予約テキスト削除・売上Excelアップロード等）を作成・修正するときは、次を必ず守る。
同じ内容が店舗PCの `C:\Users\harag\.claude\CLAUDE.md` にもある。

- **場所**：Windowsユーザー名は `harag`。作業フォルダは `C:\Users\harag\au-excel-work`。
  前のPCの `C:\Users\user\...` は使わない。ロジ発注は共有フォルダ `\\KYOYU-PC\Users\ビッグボス画像共有フォルダ\ロジ発注`。
- **pushd の一時ドライブ**：共有フォルダを `pushd` で開くと Y: や Z: が一時的に割り当てられるが、`popd` で消える。
  その「Y:\…」「Z:\…」の場所を後の処理で使わない（UNCパス `\\KYOYU-PC\Users\…` に読み替える）。
- **Python**：複数入っている。`python` で動くのは 3.12、rakuten_yoru のタスクは 3.15 を直接指定。
  **Pythonを追加・変更したら、そのPythonに `au-excel-work\requirements.txt` の部品を必ず入れる**
  （入れないと発注処理・在庫アップロード・低在庫予約が `ModuleNotFoundError` で止まる。2026-11-19 に実際に発生）。
  入れ方（PowerShell）：
  `(Get-Content C:\Users\harag\au-excel-work\requirements.txt) | ForEach-Object { ($_ -split '==')[0] } | Where-Object { $_ -and $_ -notmatch '^(pyinstaller|pyinstaller-hooks-contrib|altgraph|pefile)$' } | Set-Content $env:TEMP\req.txt; python -m pip install -r $env:TEMP\req.txt`
- **PYTHONUTF8=0**：ユーザー環境変数に設定済み。消さない（Python 3.15 の UTF-8 既定化で、バッチの `for /f` が
  日本語の場所を文字化けさせ、在庫アップロードが止まったため）。
- **.bat ファイル**：日本語を含むものは Shift-JIS（CP932）・CRLF で保存する（UTF-8 だと cmd が誤動作する）。
- **ソフトの場所**：Chrome は `C:\Program Files\Google\Chrome\Application\chrome.exe`、
  Thunderbird は `C:\Program Files\Mozilla Thunderbird\thunderbird.exe`（どちらも `(x86)` ではない）。
- **表計算ソフトは WPS**：発注表は `.xlsx` で保存する（`.et` は自動化が読み込めない）。
- **send_mail.py**：Thunderbird の作成画面を開いて Ctrl+Enter を押す方式。新PCでは作成画面を件名で探せない
  （AppActivate が失敗する）ため、「見つからなくても Ctrl+Enter を押す」動きを変えない（2026-11-18 に変えて送信が止まった）。
- **二重送信・在庫の二重加算を絶対に起こさない**：自動で送り直す・アップロードし直す仕組みは作らない。
  エラーは haraguchi@bigbossliquor.com へメールで知らせるだけにする。

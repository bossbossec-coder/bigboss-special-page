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

## au PAY マーケット 大感謝祭SALE 特集

- 場所：`au-daikansha-2026/index.html`（ユーザーが「au大感謝セール特集」「au大感謝祭」と言ったらここ）
- 店舗：酒のビッグボス au PAY マーケット店（`https://wowma.jp/user/39744535`）。商品ページは `/item/<番号>`
- 期間：2026/12/13(日)0:00〜12/16(水)9:59。全品ポイント3倍、最大500円OFFクーポン。開催カレンダーは不要（ユーザー指示）
- デザイン：赤ベースのお祭り（提灯・青海波・紙吹雪・電球の看板）。ベースは `base-blackfriday.html`（楽天ブラックフライデー、参照用に残す）
- **商品カード・カテゴリナビ・クーポンは HTML に直接書いてある**（`#cats` `#catnav` `#days`）。リンクは `href="/item/480569930"` の形で
  HTML にそのまま見えるようにする（JS で組み立てない。2026-11-25 ユーザー指示）。1ケース/2ケースは1枚のカードにまとめる。商品は80点
- クーポン：500円OFF 8,000円以上 先着100枚 / 300円OFF 5,000円以上 先着200枚 ×3日。ボタンは今はお店トップ（`/user/39744535`）。
  `<script>` は日付で「配布中」「終了」と開催状況を切り替えるのと、紙吹雪・ナビの現在地だけ（各 `.day` の `data-from` `data-to` を見る）
- 画像は `au-daikansha-2026/img/*.webp`。麦とホップ・金麦糖質75%オフ・パーフェクトビールは画像未受領（`img:''` で「画像準備中」風の枠）
- **外部リンク不可**（au 側でエラーになる。2026-11-25）：Google Fonts などの外部読み込みは使わない。
  見出し用フォント（Dela Gothic One・Archivo・Jost）は、使う文字だけに絞って `<head>` の `<style>` に base64 で埋め込み済み。
  本文は端末のゴシック体。**見出しに新しい漢字・かなを足したら、埋め込みフォントに入っていないので作り直す**
  （fonttools の subset で、ページ内の全文字＋ASCII を入れて woff2 → base64）。
  **リンクは相対パスで書く**（`https://wowma.jp/item/480569930` → `/item/480569930`、お店トップ → `/user/39744535`）。`https://` を含めない（ユーザー指示）
- **プレゼントキャンペーン**（`#present`、クーポンの下）：対象商品お買い上げで「サッポロビール満喫！飲み比べセット」あげちゃうキャンペーン。
  期間 12/1(火)〜12/29(火)、抽選30名、発表は発送をもって、当選品はお買い上げ商品と同梱。「あげちゃうキャンペーン」を一番大きく（ユーザー指示）。
  対象：黒ラベル350 1ケース `/item/480887381`・2ケース `/item/480887384`、黒ラベル500 `/item/480887430`（容量・価格は未受領なので「商品ページを見る」）
- フォント埋め込みの作り直し：`python3 au-daikansha-2026/tools/embed_fonts.py au-daikansha-2026/index.html <ttfフォルダ>`
  （ttf は Google Fonts の css2 API から古い User-Agent で取得：Dela Gothic One / Archivo wdth125 800,900 / Jost 500〜800）

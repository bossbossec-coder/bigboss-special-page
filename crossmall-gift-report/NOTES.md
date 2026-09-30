# 開発メモ(クロスモール)

`omise-net-rebate-automation/NOTES.md` の方針どおり、依頼者から各要素の
outerHTMLを受け取ってから実装した。

## 操作手順と画面要素

| 手順 | 要素 | 特定方法 |
|---|---|---|
| ログインID | `<input id="mail" type="text">` | id |
| パスワード | `<input id="dd8a78c9" type="password">` | **type=password**(idは毎回変わる可能性があるため使わない) |
| ログインボタン | `<input name="commit" type="submit" value="ログイン">` | type=submit かつ value |
| 左メニュー「注文分析」見出し | `<div id="menu7_header_hd">`(Ext JSアコーディオン、文字は&nbsp;) | id。すでに開いているときに押すと閉じるため、「商品注文」が見えないときだけ押す |
| 「商品注文」 | `<div id="menu_icon_sub" class="menu_sub">商品注文</div>` | class + 文字(idは他項目と共通の可能性) |
| 集計対象(開始) | `<input id="date_from">` 形式 `YYYY/MM/DD` | id。カレンダーは使わず直接入力 |
| 集計対象(終了) | `<input id="date_to">` | id。1日分なので開始日と同じ日付 |
| 商品名 | `<input id="item_name">` | id。「サントリー」 |
| カテゴリ1 | `<select id="main_ctgr1" onchange="chng_ctgr(2);">` | 値 982313(ギフト) |
| カテゴリ2 | `<select id="sub_ctgr1">` | 値 129397(ビール)。カテゴリ1変更で選択肢が作り直されるため、出現を待ってから選ぶ |
| 検索 | `<input name="commit" type="button" value=" 検 索 " onclick="getList();">` | onclickに getList を含むbutton |
| CSV出力 | `<span id="bbtn-btnInnerEl">CSV出力</span>` | id |

- 集計基準は既定の「注文日」のまま変更しない
- 検索結果の表示に時間がかかる場合がある → Ext JSの読み込みマスク(`.x-mask-msg`)が
  消えるのを待ち、さらに数秒待ってからCSV出力を押す(前日の結果を出力しないため)
- CSV出力を押すとすぐにダウンロードされる。ファイル名は `item_order_MMDDhhmmss.csv`
  (ダウンロードした日時)なので、`ギフト_YYYY-MM-DD.csv` に名前を変える
- Edgeの「保存場所を確認する」設定が有効だと保存ダイアログが出るため、
  `download.prompt_for_download=False` で抑止している
- 画面の一部がiframeの可能性を考慮し、要素はトップ画面とiframe内の両方から探す
- CSVの文字コードはShift_JIS(CP932)。ダウンロードしたまま変換せずに保存する

## 動作確認

実サイトにはアクセスできないため、上記HTMLを再現した模擬画面
(ログイン→メニュー→iframe内の検索画面→読み込みマスク→CSVダウンロード)で
ログイン・メニュー展開・カテゴリ2の再読み込み待ち・日付ごとの保存名・
再実行時のスキップを確認した。実サイトでの確認は必須。

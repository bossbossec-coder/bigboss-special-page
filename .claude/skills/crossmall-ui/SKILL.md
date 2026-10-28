---
name: crossmall-ui
description: クロスモール(crossmall.jp)の商品一括処理画面のボタン・入力欄の一覧(ID/セレクタ)。「クロスモールの検索ボタン」「更新ボタン」「店舗切替」「出品処理」「楽天/Yahoo/Wowmaの店舗別詳細編集」など、クロスモール画面の操作や自動化スクリプトを作る・直すときに読む。
---

# クロスモール 画面部品メモ

ユーザーから提供された実HTMLにもとづく記録。**ここにない画面・ボタンは推測せず、ユーザーにHTML(右クリック→検証→outerHTML)をもらって、このファイルに追記する。**
運用で分かったこと・ハマりどころは `crossmall-reservation-cleanup/crossmall_knowhow.md` を参照。
動作確認済みの実装は `crossmall-reservation-cleanup/reservation_cleanup.py`(確認済みの欄は ✔)。

## 共通の操作方針
- クリックは座標ではなく JS の `element.click()` を直接呼ぶ。値入力は value を設定して `input`/`change` イベントを発火。
- 検索結果は表示まで数十秒かかる。時間の目安ではなく、読み込み中表示(`.x-mask`、Ext の store)が終わるまで待つ。0件の早期確定は誤判定になる。
- JSダイアログ(confirm/alert)は CDP の `Page.handleJavaScriptDialog` で処理する。
- 店舗別詳細編集は別ウィンドウ(ポップアップ)で開く。

## 店舗ID(`#shop_id`)
| ID | 店舗 | 編集ポップアップの型 |
|---|---|---|
| 5255 | ビッグボス楽天 | 楽天 |
| 5256 | ドリームクラフト | 楽天 |
| 5257 | Yahoo | Yahoo |
| 8581 | wine.com | Yahoo |
| 8014 | Wowma | Wowma |
| 9365 | Wowma2店舗目 | Wowma |

## 商品一括処理画面
- メニュー: 「出品処理」見出し `#menu2_header_hd` → 「商品一括処理」`#menu_icon_sub.menu_sub`
- 編集対象(店舗切替): `select#shop_id`、`onchange="chngShop();"`(切替後にページ再読込) ✔
- 最終日付のクリア: `<a onclick="clearDate();">クリア</a>`
- 店舗商品名(検索): `input#item_name`(maxlength 40、部分一致) ✔
- 商品コード(検索): `input#item_cd1`〜`input#item_cd2`(範囲)、`input#item_cd_plural`(カンマ区切り複数)。前回の入力が残ると結果が絞られて0件になるため、検索前に必ず空にする ✔
- `select#stc_flag`(1=無, 2=有)。画面上は「商品登録」の欄と思われる(要確認)。予約処理では「有」 ✔
- 検索ボタン: `input[name=commit][value=" 検 索 "]`、`onclick="onSrch();"` ✔
- Mark:
  - 「追加Mark」展開: `img[src="/images/arrowdown2.gif"]`
  - 予約Claude(Mark 1100)の検索条件: `select#mark_set1100`(1=有, 2=無) ✔
  - 結果行のMark欄: `input.chk_mark#chk1100_<行>`、`onclick="chkMark6(1, '<商品内部ID>', '<商品コード>', 1100)"`。1件ずつ直接クリックでON/OFF ✔
  - Mark更新(保存): `input[name=rgst][value="更新"]`、`onclick="onSubmit();"` ✔
- 検索結果の商品名リンク: `a[href*="doEditShopItem"]`(例 `javaScript:doEditShopItem(2);`)→ 店舗別詳細編集ポップアップ ✔
- 結果行のチェック: `.x-grid-row-checker` を1つずつ直接クリック(ヘッダの全選択は使わない) ✔
- 操作リンク: 出品処理 `onUpload();` / 一括出品処理 `onMultiMallUpload();` / ダウンロード `onDownload();`
- 一括出品処理の確認画面(ポップアップまたはインライン。両対応にする): 全選択 `input[value="全選択"]`(`allRow(true);`)→ 処理開始 `input[value="処理開始"]`(`onMultipleUpload();`) ✔

## 店舗別詳細編集ポップアップ
共通: 商品名欄は `textarea[name$="[item_name]"]`、更新ボタンは `#update`。更新後にポップアップが閉じる。

**楽天・ドリームクラフト** ✔
- 商品名: `textarea#mall_rakuten_item_name`
- 在庫あり時 出荷リードタイム: `input#mall_rakuten_stock_shipping_lead_time_label`(例 SOLD OUT / IAS / BSH)
- 在庫あり時 納期管理番号: `input#mall_rakuten_stock_delivery_date_no`
- 更新: `#update`、`onclick="do_mall_item_check_and_update(this.form)"`

**Yahoo・wine.com** ✔(wine.com のIDはYahooと同じと想定。要確認)
- 商品名: `textarea#mall_yahoo_item_name`
- 更新: `#update`、`onclick="checkSelectOptions(this.form)"`

**Wowma・Wowma2店舗目** ✔
- 商品名: `textarea#mall_basic_item_name`
- 販売方法区分「通常販売」: `input#kbn_09_1`(radio、`setRadioVal('kbn_09','1')`)
- お届けリードタイムID: `input#char_13`
- 発送日ID: `input#char_12`
- 更新: `#update`、`onclick="mall_item_check_and_update(this.form)"`

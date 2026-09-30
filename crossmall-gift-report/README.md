# ギフト売上CSV 自動ダウンロードツール(クロスモール)

クロスモール(CROSS MALL)の「注文分析 > 商品注文(商品注文分析)」画面から、
1日ずつ日付を指定し、**店舗ごと**にCSVをダウンロードして
`ギフト_YYYY-MM-DD_店舗名.csv` という**集計した日の日付と店舗名入りの名前**で保存するツールです。

対象店舗(`config.json` の `shops`): ビッグボス楽天 / ドリームクラフト / Yahoo / wine.com / Wowma
(Wowma2店舗目は対象外)

- 昨年分(既定: 2025/10/15〜2025/12/31)をまとめてダウンロードできる
- 途中で止まっても、もう一度実行すればダウンロード済みの日を飛ばして続きから再開する
- `--yesterday` を付けて起動すると、前日分だけを画面入力なしでダウンロードする
  (Windowsのタスクスケジューラで毎日実行する用)

構成・ビルド方法は `omise-net-rebate-automation` と同じです。

```
crossmall-gift-report/
├── config.example.json   # 設定ファイルのひな形(コピーして config.json を作る)
├── requirements.txt
├── build_exe.bat          # exeを作るためのスクリプト
├── run_gift_csv.bat       # 起動用
├── src/
│   ├── main.py            # 処理全体の流れ(メニュー・日付・保存名・ログ)
│   ├── config.py          # 設定ファイルの読み込み
│   └── crossmall.py       # ログイン・画面操作・CSVダウンロード(Selenium + Edge)
├── USAGE.md               # 使う人向けの手順
└── NOTES.md               # 画面要素(HTML)と仕様のメモ
```

## 準備(一度だけ)

1. Python 3.11以降が入ったPCで `build_exe.bat` を実行 → `dist\GiftCsvTool.exe` ができる
2. Edgeのバージョンに合った `msedgedriver.exe` を入手する
   (https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/ )
3. `config.example.json` をコピーして `config.json` を作り、次を入力する
   - `site.login_url`: クロスモールのログイン画面のURL(既定: https://www.crossmall.jp/ )
   - `site.login_id`: ログインID
4. 次の4つを1つのフォルダにまとめる
   - `GiftCsvTool.exe` / `run_gift_csv.bat` / `config.json` / `msedgedriver.exe`

## 設定項目(config.json)

| 項目 | 内容 |
|---|---|
| `search.item_name` | 商品名に入れる文字(既定: サントリー) |
| `search.main_category_value` | カテゴリ1の値(982313 = ギフト) |
| `search.sub_category_value` | カテゴリ2の値(129397 = ビール) |
| `shops` | ダウンロードする店舗(`value` = 店舗プルダウンの値、`name` = ファイル名に使う名前) |
| `backfill.date_from` / `date_to` | まとめてダウンロードする期間 |
| `browser.headless` | `true` にするとブラウザ画面を表示せずに動く |
| `browser.search_timeout_seconds` | 検索結果の表示を待つ最大秒数 |
| `browser.wait_after_search_seconds` | 表示完了後、CSV出力を押すまでに待つ秒数 |

## パスワードについて

パスワードはファイルやプログラムには保存しません。初回の手動実行時に入力し、
希望すればWindowsの「資格情報マネージャー」に保存します
(毎日の自動実行では画面入力ができないため)。
保存したパスワードは「コントロールパネル > 資格情報マネージャー > Windows資格情報」の
`crossmall-gift-report` から削除できます。

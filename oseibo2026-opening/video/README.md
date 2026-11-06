# 2026 お歳暮 オープニング動画

- `oseibo2026-opening.mp4` … 15.0秒 / 1920×1080 / 30fps / H.264 / 音声なし
- `video.html` … アニメーションのソース（`render(t)` で t 秒の絵を描く）。絵コンテ v2（`../storyboard/`）どおりの6カット、カット間はクロスディゾルブ約0.6秒。
- 書き出し: Playwright で 450 コマを PNG 撮影 → `ffmpeg -framerate 30 -i f%04d.png -c:v libx264 -crf 18 -pix_fmt yuv420p -an`

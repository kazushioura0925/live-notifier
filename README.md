# ライブ情報通知ツール

好きなアーティストの公式サイトを1日4回チェックし、ライブ・チケット情報の新着をLINEに通知します。
チケット受付開始日時が書かれていれば、前日・30分前・開始時刻にリマインドします。

## 仕組み

| 処理 | 実行タイミング | 内容 |
|---|---|---|
| 新着チェック（`check_news.py`） | 毎日 7:17 / 12:17 / 18:17 / 22:17（日本時間） | 公式サイトのRSSを読み、新着をLINEに通知 |
| リマインド（`remind.py`） | 10分おき | 記録済みの受付開始日時を見てLINEに通知（サイトにはアクセスしない） |

GitHub Actions は混雑時に数分〜十数分遅れることがあります。

## アーティストの追加・削除

`artists.yaml` を編集します。追加するときは、公式サイトのRSS（多くは `https://サイト/feed/`）を `feed` に書きます。

## 必要な Secrets（Settings → Secrets and variables → Actions）

- `LINE_CHANNEL_ACCESS_TOKEN`：LINEのチャネルアクセストークン（長期）
- `LINE_USER_ID`：自分のユーザーID（`U` で始まる文字列）

## LINEに届くかのテスト

GitHubの「Actions」→「LINE送信テスト」→「Run workflow」で、テストメッセージを1通送れます。

## 手元でのテスト（LINEには送りません）

```
pip install -r requirements.txt
python check_news.py --dry-run --show 3
python remind.py --dry-run
```

## 記録ファイル

- `data/seen.json`：通知済みの記事（二度通知しないため）
- `data/sales.json`：チケット受付開始日時と、送信済みのリマインド

"""チケット受付開始のリマインド（10分おきに GitHub Actions から実行される）。

data/sales.json に記録された受付開始日時を見て、
  ・前日（開始の24時間前）
  ・30分前
  ・開始時刻
にLINEで知らせます。サイトにはアクセスしません。

受付開始の時刻が記事に書かれていなかった場合は、
  ・前日の20:00
  ・当日の8:00
に知らせます。

使い方:
  python remind.py             本番（LINEに送信し、記録を保存する）
  python remind.py --dry-run   テスト（LINEに送らず画面に表示。記録も保存しない）
  python remind.py --dry-run --now "2026-10-22 11:35" --sales-file テスト用.json
                               テスト用：時刻や記録ファイルを指定して試す
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import line_api
from extract import JST, fmt_dt

BASE = Path(__file__).resolve().parent
SALES_FILE = BASE / "data" / "sales.json"
KEEP_DAYS = 7   # 受付開始から何日たったら記録を消すか


def schedule(sale):
    """リマインドの予定を [(種類, 送る時刻, 見出し)] の形で返す（時刻順）。"""
    start = datetime.fromisoformat(sale["start"])
    if sale["time_known"]:
        return [
            ("day_before", start - timedelta(days=1), "明日 受付開始"),
            ("30min", start - timedelta(minutes=30), "30分後に受付開始"),
            ("start", start, "ただいま受付開始！"),
        ]
    return [
        ("day_before", start - timedelta(days=1) + timedelta(hours=20), "明日 受付開始"),
        ("day_of", start + timedelta(hours=8), "本日 受付開始"),
    ]


def due_reminder(sale, now):
    """今送るべきリマインドを1つ選ぶ。なければ None。

    GitHub Actions は実行が遅れることがあるので「予定時刻を過ぎていて、まだ送っていない」ものを送る。
    複数たまっている場合は一番新しいものだけ送り、古いものは送らずに済ませる（通知の連発を防ぐ）。
    """
    plan = schedule(sale)
    passed = [p for p in plan if p[1] <= now]
    if not passed:
        return None
    kind, when, heading = passed[-1]
    if kind in sale["sent"]:
        return None
    # 記録が遅れて当日になってから「前日」を送る場合は、見出しを「本日」にする
    start = datetime.fromisoformat(sale["start"])
    if kind == "day_before" and start.date() == now.date():
        heading = "本日 受付開始"
    # 開始時刻のお知らせは、1時間以上遅れたら送らない
    if kind == "start" and now - when > timedelta(hours=1):
        return None
    return kind, heading, [p[0] for p in passed]


def build_message(sale, heading):
    start = datetime.fromisoformat(sale["start"])
    lines = [
        f"⏰【{heading}】",
        f"🎸 {sale['artist']}",
        f"📌 {sale['show_title']}",
        f"🎫 {sale['label']}：{fmt_dt(start, sale['time_known'])}〜",
    ]
    if not sale["time_known"]:
        lines.append("※開始時刻は記事で確認してください")
    lines += ["", f"🔗 {sale['url']}"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="LINEに送らず、記録も保存しない")
    parser.add_argument("--now", help="テスト用：現在時刻を指定（例 2026-10-22 11:35）")
    parser.add_argument("--sales-file", help="テスト用：記録ファイルを指定")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    sales_file = Path(args.sales_file) if args.sales_file else SALES_FILE
    if not sales_file.exists():
        print("リマインド対象はありません")
        return
    data = json.loads(sales_file.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(args.now).replace(tzinfo=JST) if args.now else datetime.now(JST)
    if not args.dry_run and not line_api.is_configured():
        sys.exit("LINEの鍵（環境変数）が設定されていません。テストなら --dry-run を付けてください。")

    messages = []
    changed = False
    for sale in data["sales"]:
        due = due_reminder(sale, now)
        if not due:
            continue
        kind, heading, passed_kinds = due
        messages.append(build_message(sale, heading))
        # 送ったもの・飛ばしたものを「送信済み」として記録
        sale["sent"] = sorted(set(sale["sent"]) | set(passed_kinds))
        changed = True
        print(f"リマインド: {sale['artist']} {sale['label']} [{kind}]")

    # 受付開始から日数がたった記録は消す
    before = len(data["sales"])
    data["sales"] = [s for s in data["sales"]
                     if datetime.fromisoformat(s["start"]) > now - timedelta(days=KEEP_DAYS)]
    changed = changed or len(data["sales"]) != before

    if args.dry_run:
        print("\n========== LINEに送る予定のメッセージ（テストなので送信しません） ==========")
        for m in messages:
            print("\n" + m + "\n" + "-" * 40)
        if not messages:
            print("（なし）")
        return

    if messages:
        line_api.push_texts(messages)
        print(f"LINEに{len(messages)}件送信しました")
    if changed:
        sales_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print("送るリマインドはありません")


if __name__ == "__main__":
    main()

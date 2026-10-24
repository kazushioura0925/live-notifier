"""新着チェック（1日4回 GitHub Actions から実行される）。

流れ:
  1. artists.yaml に書かれた各アーティストのRSSを読む
  2. まだ通知していない記事を見つける
  3. 公演名・日程・会場・チケット受付開始日時を抜き出してLINEに通知
  4. 受付開始日時をリマインド用に data/sales.json に記録
  5. 通知した記事を data/seen.json に記録（二度通知しないため）

使い方:
  python check_news.py               本番（LINEに送信し、記録を保存する）
  python check_news.py --dry-run     テスト（LINEに送らず画面に表示。記録も保存しない）
  python check_news.py --dry-run --show 3
                                     テスト時、各サイトの最新3件を「新着」とみなして表示する
"""

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yaml

import line_api
from extract import JST, analyze, fmt_dt

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "artists.yaml"
SEEN_FILE = BASE / "data" / "seen.json"
SALES_FILE = BASE / "data" / "sales.json"

NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
SEEN_LIMIT = 300          # 記録しておく既読記事数（アーティストごと）
FAIL_ALERT_COUNT = 8      # 連続でこの回数取得に失敗したら知らせる（1日4回 × 2日）
MAX_PERF_LINES = 8        # 通知に載せる公演数の上限


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_feed(artist, state, settings, local_dir=None):
    """RSSを取得する。前回から変化がなければ None を返す。"""
    if local_dir:
        return (Path(local_dir) / f"{artist['id']}.xml").read_bytes()
    headers = {"User-Agent": settings["user_agent"]}
    # 前回と同じ内容なら中身を送らないでもらう（サイトの負担を減らす仕組み）
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    r = requests.get(artist["feed"], headers=headers, timeout=30)
    if r.status_code == 304:
        return None
    r.raise_for_status()
    state["etag"] = r.headers.get("ETag")
    state["last_modified"] = r.headers.get("Last-Modified")
    return r.content


def parse_feed(xml_bytes):
    """RSSから記事の一覧（新しい順）を取り出す。"""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        items.append({
            "id": (item.findtext("guid") or link).strip(),
            "title": (item.findtext("title") or "").strip(),
            "url": link,
            "published": parsedate_to_datetime(pub).astimezone(JST) if pub else datetime.now(JST),
            "html": item.findtext("content:encoded", namespaces=NS) or item.findtext("description") or "",
        })
    return items


def build_message(artist, item, info, now):
    """LINEに送る文章を作る。"""
    lines = [f"🎸【{artist['name']}】新着", item["title"], ""]
    lines.append(f"📌 公演名：{info['show_title']}")

    perfs = info["performances"]
    if perfs:
        lines.append("📅 日程／📍 会場：")
        for p in perfs[:MAX_PERF_LINES]:
            d = fmt_dt(p["date"], time_known=False) if p["date"] else "日程不明"
            lines.append(f"・{d}／{p['venue'] or '会場不明'}")
        if len(perfs) > MAX_PERF_LINES:
            lines.append(f"・ほか{len(perfs) - MAX_PERF_LINES}公演（記事で確認）")
    else:
        lines.append("📅 日程／📍 会場：記事で確認してください")

    sales = info["sales"]
    if sales:
        lines.append("🎫 チケット受付開始：")
        for s in sales:
            note = "（受付中）" if s["start"] <= now else ""
            time_note = "" if s["time_known"] else "（時刻は記事で確認）"
            lines.append(f"・{s['label']}　{fmt_dt(s['start'], s['time_known'])}〜{note}{time_note}")
    else:
        lines.append("🎫 チケット受付開始：記載なし／記事で確認してください")

    lines += ["", f"🔗 {item['url']}"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="LINEに送らず、記録も保存しない")
    parser.add_argument("--show", type=int, default=0, help="テスト用：最新N件を新着とみなす")
    parser.add_argument("--local", help="テスト用：RSSをサイトから取らず、このフォルダのXMLを読む")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    settings = config["settings"]
    seen_data = load_json(SEEN_FILE, {"artists": {}})
    sales_data = load_json(SALES_FILE, {"sales": []})
    now = datetime.now(JST)
    send = not args.dry_run
    if send and not line_api.is_configured():
        sys.exit("LINEの鍵（環境変数）が設定されていません。テストなら --dry-run を付けてください。")

    messages = []
    artists = [a for a in config["artists"] if a.get("enabled", True)]
    for n, artist in enumerate(artists):
        if n > 0 and not args.local:
            time.sleep(settings["wait_seconds"])  # サイトへの連続アクセスを避ける
        state = seen_data["artists"].setdefault(artist["id"], {"seen": [], "fail_count": 0})
        first_time = not state["seen"]

        try:
            xml_bytes = fetch_feed(artist, state, settings, args.local)
            items = parse_feed(xml_bytes) if xml_bytes is not None else None
        except Exception as e:  # サイトのメンテナンス・通信エラー・RSSが壊れているなど
            state["fail_count"] = state.get("fail_count", 0) + 1
            print(f"[{artist['name']}] 取得失敗（連続{state['fail_count']}回目）: {e}")
            if state["fail_count"] == FAIL_ALERT_COUNT:
                messages.append(f"⚠️【{artist['name']}】公式サイトの情報を2日間取得できていません。\n"
                                f"サイトのURL変更やメンテナンスの可能性があります。\n{artist['site']}")
            continue
        state["fail_count"] = 0
        if items is None:
            print(f"[{artist['name']}] 前回から変更なし")
            continue

        notify = True
        if args.show:
            new_items = items[:args.show]
        elif first_time:
            # 初回は過去の記事を一斉に通知しないよう、既読にするだけ。
            # ただし、これから始まるチケット受付はリマインドできるように記録する
            print(f"[{artist['name']}] 初回のため、既存の{len(items)}件を既読として記録（通知なし）")
            new_items = items
            notify = False
        else:
            new_items = [it for it in items if it["id"] not in state["seen"]]
        if notify:
            print(f"[{artist['name']}] 記事{len(items)}件／新着{len(new_items)}件")

        for item in reversed(new_items):  # 古い順に通知
            info = analyze(item["title"], item["html"], item["published"])
            if settings.get("live_only", True) and not info["is_live"]:
                if notify:
                    print(f"  - スキップ（ライブ関連ではない）: {item['title']}")
                continue
            if notify:
                messages.append(build_message(artist, item, info, now))
            # まだ始まっていない受付を、リマインド用に記録する
            for s in info["sales"]:
                if s["start"] <= now:
                    continue
                sale_id = f"{artist['id']}|{item['url']}|{s['label']}|{s['start'].isoformat()}"
                if any(x["id"] == sale_id for x in sales_data["sales"]):
                    continue
                sales_data["sales"].append({
                    "id": sale_id,
                    "artist": artist["name"],
                    "show_title": info["show_title"],
                    "label": s["label"],
                    "start": s["start"].isoformat(),
                    "time_known": s["time_known"],
                    "url": item["url"],
                    "sent": [],
                })
                print(f"  ⏰ リマインド登録: {s['label']} {fmt_dt(s['start'], s['time_known'])}")

        # 既読として記録（新しい記事を先頭に、上限を超えた古い記録は捨てる）
        ids = [it["id"] for it in items] + [x for x in state["seen"] if x not in {it["id"] for it in items}]
        state["seen"] = ids[:SEEN_LIMIT]

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
    save_json(SEEN_FILE, seen_data)
    save_json(SALES_FILE, sales_data)


if __name__ == "__main__":
    main()

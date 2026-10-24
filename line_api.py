"""LINE Messaging API でメッセージを送る処理。

鍵（チャネルアクセストークン）と送り先（ユーザーID）は、プログラムに直接書かず、
GitHub の Secrets から「環境変数」として受け取ります。
  LINE_CHANNEL_ACCESS_TOKEN : チャネルアクセストークン（長期）
  LINE_USER_ID              : あなたのユーザーID（U で始まる文字列）

送り先は2種類あります（artists.yaml の send_to で選びます）。
  me      : 自分だけに送る（push）
  friends : ボットの友だち全員に一斉送信する（broadcast）。友だちの人数分だけ無料枠を使います
"""

import os

import requests

PUSH_URL = "https://api.line.me/v2/bot/message/push"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
MAX_TEXT = 5000      # LINEの1メッセージの最大文字数
MAX_MESSAGES = 5     # 1回の送信でまとめられるメッセージ数


def is_configured():
    return bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and os.environ.get("LINE_USER_ID"))


def send_texts(texts, send_to="me"):
    """テキストを送る。5件ずつまとめて1回の送信にする（通数の節約）。"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    texts = [t[:MAX_TEXT] for t in texts if t]
    for i in range(0, len(texts), MAX_MESSAGES):
        body = {"messages": [{"type": "text", "text": t} for t in texts[i:i + MAX_MESSAGES]]}
        if send_to == "friends":
            url = BROADCAST_URL
        else:
            url = PUSH_URL
            body["to"] = os.environ["LINE_USER_ID"]
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"LINE送信に失敗しました: {r.status_code} {r.text}")


def push_texts(texts):
    """自分だけに送る（異常のお知らせ用）。"""
    send_texts(texts, send_to="me")

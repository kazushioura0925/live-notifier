"""LINE Messaging API で自分宛てにメッセージを送る処理。

鍵（チャネルアクセストークン）と送り先（ユーザーID）は、プログラムに直接書かず、
GitHub の Secrets から「環境変数」として受け取ります。
  LINE_CHANNEL_ACCESS_TOKEN : チャネルアクセストークン（長期）
  LINE_USER_ID              : あなたのユーザーID（U で始まる文字列）
"""

import os

import requests

PUSH_URL = "https://api.line.me/v2/bot/message/push"
MAX_TEXT = 5000      # LINEの1メッセージの最大文字数
MAX_MESSAGES = 5     # 1回の送信でまとめられるメッセージ数


def is_configured():
    return bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and os.environ.get("LINE_USER_ID"))


def push_texts(texts):
    """テキストを自分宛てに送る。5件ずつまとめて1回の送信にする（通数の節約）。"""
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    user_id = os.environ["LINE_USER_ID"]
    texts = [t[:MAX_TEXT] for t in texts if t]
    for i in range(0, len(texts), MAX_MESSAGES):
        chunk = texts[i:i + MAX_MESSAGES]
        r = requests.post(
            PUSH_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"to": user_id, "messages": [{"type": "text", "text": t} for t in chunk]},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"LINE送信に失敗しました: {r.status_code} {r.text}")

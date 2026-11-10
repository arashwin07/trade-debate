#!/usr/bin/env python3
"""Phone alerts (A).

  python tools/notify.py "message text"

Channels, in order:
  1. Telegram, if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set as environment variables (set them in the
     cloud environment's settings, never in chat or in this repo).
  2. Otherwise prints ALERT: <text>. In a Claude cloud routine the skill then sends it with Claude's own
     push notification to your phone (the PushNotification tool), which needs no setup.
Only final TAKE calls, fired retake conditions and data-source outages are alerted: nothing else.
"""
import json, os, sys, urllib.parse, urllib.request


def send(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20) as r:
                ok = json.loads(r.read()).get("ok")
            print("sent via Telegram" if ok else "Telegram refused the message")
            return bool(ok)
        except Exception as e:
            print(f"Telegram failed ({type(e).__name__}); falling back")
    print(f"ALERT: {text}")
    return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    send(" ".join(sys.argv[1:]) or "test alert from the trading desk")

from **future** import annotations

import os
import sys
from datetime import datetime, timezone

import requests

BOT_TOKEN = os.getenv(
"TELEGRAM_BOT_TOKEN",
""
)

CHAT_ID = os.getenv(
"TELEGRAM_CHAT_ID",
""
)

def main() -> int:

```
print("=" * 60)
print("TELEGRAM CONNECTION TEST")
print("=" * 60)

# ------------------------------------------------------------
# Check environment variables
# ------------------------------------------------------------

if not BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
    return 1

if not CHAT_ID:
    print("ERROR: TELEGRAM_CHAT_ID is missing.")
    return 1

print("Bot token configured: YES")
print("Chat ID configured: YES")

# ------------------------------------------------------------
# Test bot token
# ------------------------------------------------------------

print()
print("Testing bot token...")

get_me_url = (
    f"https://api.telegram.org/bot"
    f"{BOT_TOKEN}/getMe"
)

try:

    response = requests.get(
        get_me_url,
        timeout=20,
    )

    print(
        f"HTTP status: {response.status_code}"
    )

    data = response.json()

except Exception as exc:

    print(
        f"ERROR connecting to Telegram: "
        f"{type(exc).__name__}: {exc}"
    )

    return 1

if not data.get("ok"):

    print("Bot token test FAILED.")
    print(
        "Telegram response:",
        data
    )

    return 1

bot = data.get(
    "result",
    {}
)

bot_username = bot.get(
    "username",
    "unknown"
)

bot_first_name = bot.get(
    "first_name",
    "unknown"
)

print("Bot token test: SUCCESS")
print(
    f"Bot name: {bot_first_name}"
)
print(
    f"Bot username: @{bot_username}"
)

# ------------------------------------------------------------
# Build Telegram message
# ------------------------------------------------------------

timestamp = datetime.now(
    timezone.utc
).strftime(
    "%Y-%m-%d %H:%M:%S UTC"
)

message = (
    "✅ TELEGRAM TEST SUCCESS\n\n"
    "GitHub Actions successfully connected "
    "to this Telegram bot.\n\n"
    f"Test time: {timestamp}\n\n"
    "This message was sent by "
    "test_telegram.py."
)

# ------------------------------------------------------------
# SHOW EXACT TELEGRAM MESSAGE IN GITHUB LOG
# ------------------------------------------------------------

print()
print("=" * 60)
print("MESSAGE THAT WILL BE SENT TO TELEGRAM")
print("=" * 60)
print(message)
print("=" * 60)

# ------------------------------------------------------------
# Send Telegram message
# ------------------------------------------------------------

print()
print("Sending test message...")

send_url = (
    f"https://api.telegram.org/bot"
    f"{BOT_TOKEN}/sendMessage"
)

payload = {
    "chat_id": CHAT_ID,
    "text": message,
    "disable_web_page_preview": True,
}

try:

    response = requests.post(
        send_url,
        json=payload,
        timeout=20,
    )

    print(
        f"HTTP status: {response.status_code}"
    )

    data = response.json()

except Exception as exc:

    print(
        f"ERROR sending Telegram message: "
        f"{type(exc).__name__}: {exc}"
    )

    return 1

# ------------------------------------------------------------
# Validate Telegram response
# ------------------------------------------------------------

if not data.get("ok"):

    print()
    print("Telegram message FAILED.")
    print("Telegram response:")
    print(data)

    return 1

result = data.get(
    "result",
    {}
)

message_id = result.get(
    "message_id",
    "unknown"
)

print()
print("=" * 60)
print("TELEGRAM MESSAGE SENT SUCCESSFULLY")
print("=" * 60)
print(
    f"Message ID: {message_id}"
)
print()
print(
    "The message above is the exact text "
    "sent to Telegram."
)
print("=" * 60)

return 0
```

if **name** == "**main**":
sys.exit(main())

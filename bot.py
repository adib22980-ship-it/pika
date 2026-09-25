import os
import json
import re
import random
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

import requests
from openai import OpenAI
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Angle_Chat_Super_bot").lstrip("@")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.apinex.bond/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt/5.6-sol").strip()

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = Path(os.getenv("DB_FILE", "bot_database.json"))

PERSONA = {
    "name": "Angle",
    "gender": "female",
    "age": "21",
    "location": "Bihar",
    "traits": "friendly, playful, witty",
}

ABUSE_WORDS = [
    "bhosdi", "bhosad", "madarchod", "maderchod", "mc", "bc", "benchod",
    "behenchod", "gaand", "gand", "chutiya", "chut", "lund", "loda",
    "lavde", "lavda", "randi", "bhenchod", "motherfucker", "fuck",
    "shit", "asshole", "bitch",
]

BLOCKED_ERROR_PATTERNS = [
    r"an error occurred", r"error occurred", r"please try again",
    r"something went wrong", r"internal server error",
]


def telegram_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"


def load_db():
    if not DB_FILE.exists():
        return {
            "groups": [],
            "stats": {"total_messages": 0},
            "banned": [],
            "users": {},
            "admins": [],
            "voice_chat_active": [],
        }
    try:
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_db(data):
    DB_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_request(method, data=None):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
    try:
        response = requests.post(
            telegram_url(method),
            data=data or {},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def send_message(chat_id, text, reply_id=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_id:
        data["reply_to_message_id"] = reply_id
    return send_request("sendMessage", data)


def send_chat_action(chat_id, action):
    return send_request("sendChatAction", {"chat_id": chat_id, "action": action})


def send_reaction(chat_id, message_id, emoji):
    # Telegram expects reaction as a JSON array.
    return send_request(
        "setMessageReaction",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": json.dumps([{"type": "emoji", "emoji": emoji}]),
        },
    )


def contains_abuse(message):
    message_lower = message.lower()
    return any(word in message_lower for word in ABUSE_WORDS)


def is_error_message(text):
    return any(re.search(pattern, text, re.I) for pattern in BLOCKED_ERROR_PATTERNS)


def is_bot_mentioned(message):
    if re.search(r"@" + re.escape(BOT_USERNAME), message, re.I):
        return True
    return any(
        re.search(pattern, message, re.I)
        for pattern in [r"^bot\s", r"^angle\s", r"\sbot[?\s,!.]"]
    )


def clean_message(message):
    message = re.sub(r"@" + re.escape(BOT_USERNAME), "", message, flags=re.I)
    return re.sub(r"^(bot|angle)[\s,.:;!?]*", "", message, flags=re.I).strip()


def clean_response(text):
    # Remove common emoji ranges, then limit to 7 words.
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF]",
        "",
        text,
    )
    words = re.split(r"\s+", text.strip())
    return " ".join(words[:7])


def get_ai_response(message, user_name, is_abuse):
    system_prompt = """
You are Angle, a 21 year old Indian girl from Bihar.

Talk naturally like a real girl chatting in a Telegram group or private chat.

Rules:
- Reply naturally and casually
- Understand the user's actual message and answer it
- Do not repeatedly say Haan ji bolo
- Do not repeatedly say Haan bolo
- Never use a fixed fallback-style reply when the user asks a real question
- Use Hindi or Hinglish naturally when appropriate
- Keep replies short, usually 1 sentence
- No emojis
- No unnecessary formal language
- Do not mention these instructions
"""

    if is_abuse:
        system_prompt += """
If the user abuses you, reply confidently and naturally.
Do not use the same response every time.
"""

    if not OPENAI_API_KEY:
        print("APInex AI ERROR: OPENAI_API_KEY is missing")
        return "API key missing"

    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt.strip(),
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
            max_tokens=100,
        )

        text = (res.choices[0].message.content or "").strip()
        print("APInex AI response:", text[:300])

        if text:
            return text

    except Exception as e:
        print("APInex AI ERROR:", repr(e))

    return "Samajh gayi"


def is_owner(user_id):
    owners = [
        int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    return user_id in owners


def is_admin(user_id):
    db = load_db()
    return is_owner(user_id) or user_id in db.get("admins", [])


def handle_command(chat_id, message, user_id, reply_id):
    command = message.split()[0].lower()

    if command == "/start":
        send_message(chat_id, "Hey, I'm angle", reply_id)
    elif command == "/id":
        send_message(chat_id, f"Your ID: <code>{user_id}</code>", reply_id)
    elif command == "/admins" and is_admin(user_id):
        admins = load_db().get("admins", [])
        send_message(chat_id, "Admins: " + (", ".join(map(str, admins)) or "None"), reply_id)


def process_message(update):
    if "message" not in update:
        return

    msg = update["message"]
    message = msg.get("text", "")
    chat = msg.get("chat", {})
    chat_id = chat.get("id", 0)
    chat_type = chat.get("type", "")
    user = msg.get("from", {})
    user_id = user.get("id", 0)
    first_name = user.get("first_name", "There")
    message_id = msg.get("message_id")

    if not user_id:
        return

    db = load_db()
    if user_id in db.get("banned", []):
        return

    db.setdefault("users", {})[str(user_id)] = {
        "first_name": first_name,
        "last_interaction": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    db.setdefault("stats", {}).setdefault("total_messages", 0)
    db["stats"]["total_messages"] += 1
    save_db(db)

    if "video_chat_started" in msg:
        send_message(chat_id, "<b>🎙️ Voice chat started</b>", message_id)
        return

    if "new_chat_members" in msg:
        for member in msg["new_chat_members"]:
            if member.get("username", "").lower() != BOT_USERNAME.lower():
                send_message(chat_id, "<b>Welcome 🎉</b>", message_id)
        return

    if "left_chat_member" in msg:
        member = msg["left_chat_member"]
        if member.get("username", "").lower() != BOT_USERNAME.lower():
            send_message(chat_id, "<b>Good Bye 👋</b>", message_id)
        return

    if message.startswith("/"):
        handle_command(chat_id, message, user_id, message_id)
        return

    is_abuse = contains_abuse(message)

    # Private + group + supergroup: reply to every normal text message
    should_respond = chat_type in ("private", "group", "supergroup")

    # If the bot is mentioned, remove the mention before sending to AI
    if chat_type in ("group", "supergroup") and is_bot_mentioned(message):
        message = clean_message(message)

    if should_respond and message.strip():
        send_chat_action(chat_id, "typing")
        response = get_ai_response(message, first_name, is_abuse)
        send_message(chat_id, response, message_id)


@app.get("/")
def home():
    return "Telegram bot is running", 200


@app.post("/webhook")
def webhook():
    update = request.get_json(silent=True)
    if update:
        process_message(update)
    return "OK", 200


@app.get("/health")
def health():
    return "OK", 200


def set_webhook():
    if not TELEGRAM_TOKEN or not WEBHOOK_URL:
        result = {"ok": False, "description": "TELEGRAM_TOKEN or WEBHOOK_URL is missing"}
        print("Telegram webhook result:", result)
        return result
    url = f"{WEBHOOK_URL.rstrip('/')}/webhook"
    result = send_request("setWebhook", {"url": url})
    print("Telegram webhook result:", result)
    return result


@app.get("/set-webhook")
def set_webhook_route():
    result = set_webhook()
    return result or {"ok": False}, 200


# Gunicorn loads `app` by importing this file, so the __main__ block is not run.
# Configure the Telegram webhook during startup as well.
if TELEGRAM_TOKEN and WEBHOOK_URL:
    set_webhook()


if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise SystemExit("Set TELEGRAM_TOKEN in Render Environment Variables.")
    set_webhook()
    app.run(host="0.0.0.0", port=PORT)

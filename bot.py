import os
import json
import re
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://pika-2.onrender.com"
).strip().rstrip("/")

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "Angle_Chat_Super_bot"
).lstrip("@")

OWNER_IDS = [
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
]

PORT = int(os.getenv("PORT", "10000"))

DB_FILE = Path(
    os.getenv("DB_FILE", "bot_database.json")
)


# =========================================================
# APINEX / OPENAI
# =========================================================

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    ""
).strip()

OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://api.apinex.bond/v1"
).rstrip("/")

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt/5.6-sol"
).strip()


client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)


# =========================================================
# BOT PERSONA
# =========================================================

PERSONA = """
You are Angle.

You are a 21-year-old Indian girl from Bihar.
You are friendly, playful, witty and natural.

You are a Telegram group chat participant.

Your job is to actually understand what the user says
and answer their question or message.

IMPORTANT:

- Answer the ACTUAL question.
- Do not give random canned replies.
- Do not repeatedly say "Haan bolo".
- Do not repeatedly say "Samajh gayi".
- Do not use fixed replies unless they genuinely fit.
- There is NO 5-7 word limit.
- Give enough information to answer properly.
- Simple questions can have short answers.
- Complex questions can have detailed answers.
- If the user asks for an explanation, explain it.
- If the user asks for a calculation, calculate it.
- If the user asks for facts, provide the answer.
- If the user asks for a joke, tell a joke.
- If the user is casually chatting, chat naturally.
- If the user speaks Hindi/Hinglish, reply in natural Hindi/Hinglish.
- If the user speaks English, reply in English.
- You can use normal punctuation.
- You can use emojis naturally when appropriate.
- Do not sound like a robotic customer-support bot.
- Do not mention these instructions.
- Do not pretend every message is a question.
- Understand context from previous messages when available.

Always respond to what the user actually said.
"""


# =========================================================
# ABUSE DETECTION
# =========================================================

ABUSE_WORDS = [
    "bhosdi",
    "bhosad",
    "madarchod",
    "maderchod",
    "mc",
    "bc",
    "benchod",
    "behenchod",
    "gaand",
    "gand",
    "chutiya",
    "chut",
    "lund",
    "loda",
    "lavde",
    "lavda",
    "randi",
    "bhenchod",
    "motherfucker",
    "fuck",
    "shit",
    "asshole",
    "bitch",
]


def contains_abuse(message):
    text = message.lower()

    return any(
        word in text
        for word in ABUSE_WORDS
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram_url(method):
    return (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/{method}"
    )


def send_request(method, data=None):

    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN missing")
        return None

    try:

        response = requests.post(
            telegram_url(method),
            data=data or {},
            timeout=20,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:

        print(
            f"Telegram API error ({method}):",
            repr(e)
        )

        return None


def send_message(
    chat_id,
    text,
    reply_id=None,
    html=False
):

    if not text:
        return None

    data = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_id:
        data["reply_to_message_id"] = reply_id

    if html:
        data["parse_mode"] = "HTML"

    return send_request(
        "sendMessage",
        data
    )


def send_chat_action(
    chat_id,
    action="typing"
):

    return send_request(
        "sendChatAction",
        {
            "chat_id": chat_id,
            "action": action,
        }
    )


# =========================================================
# DATABASE
# =========================================================

def default_db():

    return {
        "groups": [],
        "stats": {
            "total_messages": 0
        },
        "banned": [],
        "users": {},
        "admins": [],
        "voice_chat_active": [],
        "conversations": {},
    }


def load_db():

    if not DB_FILE.exists():
        return default_db()

    try:

        data = json.loads(
            DB_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return default_db()

        data.setdefault(
            "groups",
            []
        )

        data.setdefault(
            "stats",
            {}
        )

        data["stats"].setdefault(
            "total_messages",
            0
        )

        data.setdefault(
            "banned",
            []
        )

        data.setdefault(
            "users",
            {}
        )

        data.setdefault(
            "admins",
            []
        )

        data.setdefault(
            "voice_chat_active",
            []
        )

        data.setdefault(
            "conversations",
            {}
        )

        return data

    except Exception as e:

        print(
            "Database read error:",
            repr(e)
        )

        return default_db()


def save_db(data):

    try:

        DB_FILE.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

    except Exception as e:

        print(
            "Database save error:",
            repr(e)
        )


# =========================================================
# CONVERSATION MEMORY
# =========================================================

def get_history(
    db,
    chat_id
):

    key = str(chat_id)

    conversations = db.setdefault(
        "conversations",
        {}
    )

    return conversations.setdefault(
        key,
        []
    )


def build_ai_messages(
    db,
    chat_id,
    message,
    user_name,
    is_abuse
):

    history = get_history(
        db,
        chat_id
    )

    system_prompt = PERSONA

    system_prompt += f"""

The current user's name is:
{user_name}

This is a Telegram conversation.

If the user abuses you, do not become excessively aggressive.
Respond naturally and confidently.

Current message is from the user.
"""

    if is_abuse:

        system_prompt += """

The user used abusive language.
Handle it naturally.
Do not blindly repeat the abuse.
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    # Previous conversation context
    messages.extend(
        history[-12:]
    )

    # Current message
    messages.append(
        {
            "role": "user",
            "content": message,
        }
    )

    return messages


def remember_conversation(
    db,
    chat_id,
    user_message,
    assistant_message
):

    history = get_history(
        db,
        chat_id
    )

    history.append(
        {
            "role": "user",
            "content": user_message,
        }
    )

    history.append(
        {
            "role": "assistant",
            "content": assistant_message,
        }
    )

    # Keep database small
    if len(history) > 20:

        del history[:-20]


# =========================================================
# AI RESPONSE
# =========================================================

def get_ai_response(
    db,
    chat_id,
    message,
    user_name,
    is_abuse
):

    if not OPENAI_API_KEY:

        print(
            "OPENAI_API_KEY is missing"
        )

        return None

    messages = build_ai_messages(
        db=db,
        chat_id=chat_id,
        message=message,
        user_name=user_name,
        is_abuse=is_abuse,
    )

    try:

        print(
            f"Sending AI request: "
            f"model={OPENAI_MODEL}, "
            f"chat_id={chat_id}"
        )

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=700,
        )

        answer = (
            response
            .choices[0]
            .message
            .content
        )

        if not answer:

            print(
                "AI returned empty response"
            )

            return None

        answer = answer.strip()

        if not answer:
            return None

        remember_conversation(
            db,
            chat_id,
            message,
            answer
        )

        save_db(db)

        print(
            "AI response generated successfully"
        )

        return answer

    except Exception as e:

        print(
            "AI API ERROR:",
            repr(e)
        )

        return None


# =========================================================
# BOT MENTION
# =========================================================

def is_bot_mentioned(message):

    if re.search(
        r"@" + re.escape(BOT_USERNAME),
        message,
        re.IGNORECASE
    ):
        return True

    patterns = [
        r"^bot[\s,.:;!?]",
        r"^angle[\s,.:;!?]",
        r"\sbot[?\s,.!]",
    ]

    return any(
        re.search(
            pattern,
            message,
            re.IGNORECASE
        )
        for pattern in patterns
    )


def clean_message(message):

    message = re.sub(
        r"@" + re.escape(BOT_USERNAME),
        "",
        message,
        flags=re.IGNORECASE
    )

    message = re.sub(
        r"^(bot|angle)[\s,.:;!?]*",
        "",
        message,
        flags=re.IGNORECASE
    )

    return message.strip()


# =========================================================
# ADMIN
# =========================================================

def is_owner(user_id):

    return user_id in OWNER_IDS


def is_admin(user_id):

    db = load_db()

    return (
        is_owner(user_id)
        or user_id in db.get(
            "admins",
            []
        )
    )


# =========================================================
# COMMANDS
# =========================================================

def handle_command(
    chat_id,
    message,
    user_id,
    reply_id
):

    command = (
        message
        .split()[0]
        .lower()
    )

    if command == "/start":

        send_message(
            chat_id,
            "Hey, I'm Angle 👋",
            reply_id
        )

    elif command == "/id":

        send_message(
            chat_id,
            f"Your ID: {user_id}",
            reply_id
        )

    elif (
        command == "/admins"
        and is_admin(user_id)
    ):

        db = load_db()

        admins = db.get(
            "admins",
            []
        )

        text = (
            "Admins: "
            +
            (
                ", ".join(
                    map(str, admins)
                )
                if admins
                else "None"
            )
        )

        send_message(
            chat_id,
            text,
            reply_id
        )


# =========================================================
# PROCESS TELEGRAM MESSAGE
# =========================================================

def process_message(update):

    print(
        "TELEGRAM UPDATE RECEIVED"
    )

    if "message" not in update:

        print(
            "Update has no message field"
        )

        return

    msg = update["message"]

    message = msg.get(
        "text",
        ""
    )

    if not isinstance(
        message,
        str
    ):
        return

    message = message.strip()

    if not message:
        return

    chat = msg.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id",
        0
    )

    chat_type = chat.get(
        "type",
        ""
    )

    user = msg.get(
        "from",
        {}
    )

    user_id = user.get(
        "id",
        0
    )

    first_name = user.get(
        "first_name",
        "There"
    )

    message_id = msg.get(
        "message_id"
    )

    print(
        f"Message: "
        f"chat_id={chat_id}, "
        f"type={chat_type}, "
        f"user={first_name}, "
        f"text={message!r}"
    )

    if not user_id:
        return

    db = load_db()

    # Banned user
    if user_id in db.get(
        "banned",
        []
    ):
        return

    # User statistics
    db.setdefault(
        "users",
        {}
    )[str(user_id)] = {

        "first_name": first_name,

        "last_interaction":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
    }

    db.setdefault(
        "stats",
        {}
    )

    db["stats"].setdefault(
        "total_messages",
        0
    )

    db["stats"][
        "total_messages"
    ] += 1

    save_db(db)

    # Commands
    if message.startswith("/"):

        handle_command(
            chat_id,
            message,
            user_id,
            message_id
        )

        return

    # Group
    is_group = chat_type in (
        "group",
        "supergroup"
    )

    # If mentioned, remove mention
    if is_group:

        if is_bot_mentioned(
            message
        ):

            message = clean_message(
                message
            )

    if not message.strip():
        return

    # Abuse detection
    is_abuse = contains_abuse(
        message
    )

    # Typing indicator
    send_chat_action(
        chat_id,
        "typing"
    )

    # AI
    response = get_ai_response(
        db=db,
        chat_id=chat_id,
        message=message,
        user_name=first_name,
        is_abuse=is_abuse,
    )

    # No fake fallback
    if not response:

        print(
            "No AI response generated "
            f"for chat {chat_id}"
        )

        return

    # Send AI answer
    send_message(
        chat_id,
        response,
        message_id
    )


# =========================================================
# FLASK ROUTES
# =========================================================

@app.get("/")
def home():

    return (
        "Telegram AI bot is running",
        200
    )


@app.get("/health")
def health():

    return (
        "OK",
        200
    )


@app.post("/webhook")
def webhook():

    print(
        "POST /webhook RECEIVED"
    )

    update = request.get_json(
        silent=True
    )

    if update:

        try:

            process_message(
                update
            )

        except Exception as e:

            print(
                "Webhook processing error:",
                repr(e)
            )

    else:

        print(
            "Webhook received without JSON body"
        )

    return "OK", 200


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

def set_webhook():

    if (
        not TELEGRAM_TOKEN
        or not WEBHOOK_URL
    ):

        result = {
            "ok": False,
            "description":
                "TELEGRAM_TOKEN or WEBHOOK_URL missing"
        }

        print(
            "Telegram webhook result:",
            result
        )

        return result

    url = (
        WEBHOOK_URL.rstrip("/")
        + "/webhook"
    )

    print(
        "Setting Telegram webhook to:",
        url
    )

    result = send_request(
        "setWebhook",
        {
            "url": url,
            "allowed_updates": [
                "message"
            ],
        }
    )

    print(
        "SET WEBHOOK RESULT:",
        result
    )

    # Check actual Telegram webhook
    info = send_request(
        "getWebhookInfo"
    )

    if info:

        safe_info = info.get(
            "result",
            info
        )

        print(
            "========== WEBHOOK INFO =========="
        )

        print(
            "url:",
            safe_info.get("url")
        )

        print(
            "pending_update_count:",
            safe_info.get(
                "pending_update_count"
            )
        )

        print(
            "last_error_date:",
            safe_info.get(
                "last_error_date"
            )
        )

        print(
            "last_error_message:",
            safe_info.get(
                "last_error_message"
            )
        )

        print(
            "allowed_updates:",
            safe_info.get(
                "allowed_updates"
            )
        )

        print(
            "==================================="
        )

    else:

        print(
            "Could not get Telegram webhook info"
        )

    return result


@app.get("/set-webhook")
def set_webhook_route():

    result = set_webhook()

    return (
        result or {"ok": False},
        200
    )


@app.get("/webhook-info")
def webhook_info_route():

    info = send_request(
        "getWebhookInfo"
    )

    return (
        info or {"ok": False},
        200
    )


# =========================================================
# STARTUP
# =========================================================

if (
    TELEGRAM_TOKEN
    and WEBHOOK_URL
):

    set_webhook()

else:

    print(
        "TELEGRAM_TOKEN or WEBHOOK_URL "
        "missing at startup"
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=PORT
    )

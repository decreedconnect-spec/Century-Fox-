import os
import time
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import openai
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RESEMBLE_API_KEY = os.getenv("RESEMBLE_API_KEY")
RESEMBLE_VOICE_ID = os.getenv("RESEMBLE_VOICE_ID")
RESEMBLE_PROJECT_ID = os.getenv("RESEMBLE_PROJECT_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not all([OPENAI_API_KEY, TELEGRAM_TOKEN, RESEMBLE_API_KEY, RESEMBLE_VOICE_ID, RESEMBLE_PROJECT_ID, CHANNEL_ID]):
    raise SystemExit("Missing one or more required environment variables. See .env.example")

openai.api_key = OPENAI_API_KEY

post_queue = []
user_voice_mode = {}

# ----------------------------
# DESIGN / TEMPLATE
# ----------------------------
def century_fox_caption(title: str, message: str, link: str) -> str:
    return f"""
<b>🎬 CENTURY-FOX</b>

<b>{title}</b>

{message}

<a href="{link}">🔗 Read more</a>
"""

def buttons_template() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📌 Follow", url="https://t.me/your_channel"),
            InlineKeyboardButton("📰 Latest", url="https://t.me/your_channel")
        ],
        [
            InlineKeyboardButton("🌐 Website", url="https://example.com"),
            InlineKeyboardButton("🎥 Trailer", url="https://example.com/trailer")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ----------------------------
# OpenAI Prompt
# ----------------------------
DEFAULT_BEHAVIOR = """
You are a business assistant with the emotional depth and calm confidence of 4KP.
You speak like a strong, supportive leader who is kind but direct.
Tone: Calm, confident, emotional, professional, actionable.
Rules: No lecturing. Always give next steps.
"""

# ----------------------------
# OpenAI chat
# ----------------------------
async def chat_with_openai(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=prompt,
        max_tokens=400,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# ----------------------------
# Resemble voice
# ----------------------------
def generate_voice(text: str, timeout_seconds: int = 30) -> str:
    url = f"https://api.resemble.ai/v1/projects/{RESEMBLE_PROJECT_ID}/clips"
    headers = {"Authorization": f"Token {RESEMBLE_API_KEY}", "Content-Type": "application/json"}
    data = {"voice": RESEMBLE_VOICE_ID, "title": "Voice Note", "body": text}

    res = requests.post(url, headers=headers, json=data, timeout=10)
    res.raise_for_status()
    clip_id = res.json()["id"]

    start = time.time()
    while True:
        status = requests.get(f"{url}/{clip_id}", headers=headers, timeout=10)
        status.raise_for_status()
        status_json = status.json()

        if status_json.get("status") == "done":
            return status_json.get("download_url")

        if time.time() - start > timeout_seconds:
            raise TimeoutError("Voice generation timed out")
        time.sleep(2)

# ----------------------------
# Command handlers
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Century-Fox Auto Post Bot.\n"
        "Use /post to schedule posts.\n"
        "Use /voice_on to send voice notes.\n"
        "Use /voice_off to stop voice mode.\n"
        "Use /queue to view scheduled posts.\n\n"
        "Post format:\n"
        "/post title | message | link | minutes_from_now"
    )

async def voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_voice_mode[update.message.from_user.id] = True
    await update.message.reply_text("Voice mode ON. Your messages will be sent as voice notes.")

async def voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_voice_mode[update.message.from_user.id] = False
    await update.message.reply_text("Voice mode OFF. Your messages will be sent as text.")

async def queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not post_queue:
        await update.message.reply_text("Queue is empty.")
        return
    text = "Scheduled Posts:\n"
    for i, item in enumerate(post_queue):
        text += f"{i+1}. {item['title']} at {item['time']}\n"
    await update.message.reply_text(text)

async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text or "|" not in update.message.text:
        await update.message.reply_text("Invalid format. Use:\n/post title | message | link | minutes")
        return

    try:
        _, payload = update.message.text.split(" ", 1)
        title, message, link, minutes = [x.strip() for x in payload.split("|", 3)]
        schedule_time = datetime.now() + timedelta(minutes=int(minutes))
    except Exception:
        await update.message.reply_text("Invalid format. Use:\n/post title | message | link | minutes")
        return

    post_queue.append({
        "title": title,
        "message": message,
        "link": link,
        "time": schedule_time.strftime("%Y-%m-%d %H:%M:%S")
    })

    await update.message.reply_text(f"Post scheduled for {schedule_time}")

# ----------------------------
# Auto-post loop
# ----------------------------
async def auto_post_loop(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for post_item in post_queue[:]:
        post_time = datetime.strptime(post_item["time"], "%Y-%m-%d %H:%M:%S")
        if now >= post_time:
            caption = century_fox_caption(post_item["title"], post_item["message"], post_item["link"])
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo="https://i.imgur.com/your_default_image.jpg",
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons_template()
            )
            post_queue.remove(post_item)

# ----------------------------
# Message handler
# ----------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if user_voice_mode.get(user_id, False):
        voice_url = generate_voice(text)
        await update.message.reply_voice(voice=voice_url)
        return

    prompt = [
        {"role": "system", "content": DEFAULT_BEHAVIOR},
        {"role": "user", "content": text}
    ]
    ai_response = await chat_with_openai(prompt)
    await update.message.reply_text(ai_response)

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", post))
    app.add_handler(CommandHandler("queue", queue))
    app.add_handler(CommandHandler("voice_on", voice_on))
    app.add_handler(CommandHandler("voice_off", voice_off))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(auto_post_loop, interval=10, first=10)

    print("Bot is running...")
    app.run_polling()

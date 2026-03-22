import logging
import redis
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ==================== الإعدادات ====================
TOKEN = "8364586664:AAFMu0Kg8Fyvcuuc2YUGdyU2uBwplPI5wak"
ADMIN_GROUP_ID = -4877428126
OWNER_ID = 6888898698

REDIS_HOST = "redis-18716.c244.us-east-1-2.ec2.cloud.redislabs.com"
REDIS_PORT = 18716
REDIS_PASSWORD = "fKKKwO2rExeB4jWXNMxCEVcXibRdbXiz"
REDIS_PREFIX = "bot2"

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Web Server ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        pass

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

# ==================== Redis ====================
def save_user(user_id): r.sadd(f"{REDIS_PREFIX}:users", user_id)
def get_all_users(): return list(r.smembers(f"{REDIS_PREFIX}:users"))
def get_users_count(): return r.scard(f"{REDIS_PREFIX}:users")
def get_messages_count(): return len(r.keys(f"{REDIS_PREFIX}:msg:*"))

def save_message_map(group_msg_id, user_id):
    r.set(f"{REDIS_PREFIX}:msg:{group_msg_id}", user_id, ex=18000)

def get_user_from_message(group_msg_id):
    return r.get(f"{REDIS_PREFIX}:msg:{group_msg_id}")

def ban_user(user_id): r.sadd(f"{REDIS_PREFIX}:banned", user_id)
def unban_user(user_id): r.srem(f"{REDIS_PREFIX}:banned", user_id)
def is_banned(user_id): return r.sismember(f"{REDIS_PREFIX}:banned", str(user_id))
def get_banned_count(): return r.scard(f"{REDIS_PREFIX}:banned")

def is_first_message(user_id):
    return not r.sismember(f"{REDIS_PREFIX}:messaged", str(user_id))

def mark_messaged(user_id):
    r.sadd(f"{REDIS_PREFIX}:messaged", user_id)

# ==================== مساعد ====================
def get_user_display(user):
    return f"@{user.username}" if user.username else user.first_name

# ==================== /start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("🚫 تم حظرك من استخدام البوت.")
        return
    save_user(user.id)
    await update.message.reply_text(f"أهلاً {user.first_name}! 👋")

# ==================== رسائل المستخدم ====================
async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user = update.message.from_user
    user_id = user.id

    if is_banned(user_id):
        await update.message.reply_text("🚫 تم حظرك من استخدام البوت.")
        return

    save_user(user_id)
    first_time = is_first_message(user_id)
    sender_name = get_user_display(user)
    msg = update.message

    try:
        # 👤 الرسالة الأولى (فقط اليوزر)
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=f"👤 مستخدم: {sender_name}"
        )

        # 📩 الرسالة الثانية (بدون يوزر)
        sent = await context.bot.copy_message(
            chat_id=ADMIN_GROUP_ID,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id
        )

        save_message_map(sent.message_id, user_id)

        if first_time:
            await update.message.reply_text("✅ سنرد عليك في أقرب وقت ممكن.")
            mark_messaged(user_id)

    except Exception as e:
        logger.error(f"❌ خطأ: {e}", exc_info=True)

# ==================== رد الأدمن ====================
async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return
    if not update.message.reply_to_message:
        return

    replied_id = update.message.reply_to_message.message_id
    target_user_id = get_user_from_message(replied_id)

    if not target_user_id:
        return

    target_user_id = int(target_user_id)
    msg = update.message

    try:
        if msg.text:
            await context.bot.send_message(chat_id=target_user_id, text=f"📨 رد من الإدارة:\n\n{msg.text}")
        elif msg.photo:
            await context.bot.send_photo(chat_id=target_user_id, photo=msg.photo[-1].file_id, caption=msg.caption)
        elif msg.video:
            await context.bot.send_video(chat_id=target_user_id, video=msg.video.file_id, caption=msg.caption)
        elif msg.voice:
            await context.bot.send_voice(chat_id=target_user_id, voice=msg.voice.file_id)
        elif msg.audio:
            await context.bot.send_audio(chat_id=target_user_id, audio=msg.audio.file_id, caption=msg.caption)
        elif msg.document:
            await context.bot.send_document(chat_id=target_user_id, document=msg.document.file_id, caption=msg.caption)
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=target_user_id, sticker=msg.sticker.file_id)
        elif msg.video_note:
            await context.bot.send_video_note(chat_id=target_user_id, video_note=msg.video_note.file_id)
        else:
            await update.message.reply_text("❌ نوع غير مدعوم")
            return

        await update.message.reply_text("✅ تم إرسال الرد!")

    except Exception as e:
        logger.error(f"❌ خطأ: {e}", exc_info=True)

# ==================== أوامر ====================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return
    await update.message.reply_text(
        f"📊 المستخدمين: {get_users_count()}\n"
        f"📨 الرسائل: {get_messages_count()}\n"
        f"🚫 المحظورين: {get_banned_count()}"
    )

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("❌ لا يوجد مستخدمين")
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("❌ اكتب الرسالة بعد الأمر")
        return

    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text)
        except:
            pass

    await update.message.reply_text("✅ تم البث")

# ==================== التشغيل ====================
ALL_MESSAGES = (
    filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
    filters.AUDIO | filters.VIDEO_NOTE | filters.Sticker.ALL |
    filters.ANIMATION | filters.Document.ALL
)

def main():
    try:
        r.ping()
        logger.info("✅ Redis متصل")
    except Exception as e:
        logger.error(f"❌ Redis error: {e}")
        return

    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("bd", broadcast_cmd))

    app.add_handler(MessageHandler(
        filters.Chat(ADMIN_GROUP_ID) & ALL_MESSAGES,
        handle_group_reply
    ))

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ALL_MESSAGES,
        handle_private_message
    ))

    logger.info("✅ البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

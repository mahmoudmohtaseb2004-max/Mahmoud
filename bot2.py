import logging
import redis
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
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


# ==================== Web Server عشان Render ما ينام ====================

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


# ==================== دوال Redis ====================

def save_user(user_id): r.sadd(f"{REDIS_PREFIX}:users", user_id)
def get_all_users(): return list(r.smembers(f"{REDIS_PREFIX}:users"))
def get_users_count(): return r.scard(f"{REDIS_PREFIX}:users")
def get_messages_count(): return len(r.keys(f"{REDIS_PREFIX}:msg:*"))

def save_message_map(group_msg_id, user_id):
    r.set(f"{REDIS_PREFIX}:msg:{group_msg_id}", user_id, ex=18000)  # تنمسح بعد 5 ساعات

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

def get_iraq_time():
    tz = pytz.timezone('Asia/Baghdad')
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

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


# ==================== رسائل المستخدمين ====================

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
    now = get_iraq_time()
    msg = update.message

    try:
        # تحويل الرسالة مباشرة للجروب
        sent = await msg.forward(chat_id=ADMIN_GROUP_ID)

        # حفظ العلاقة بين رسالة الجروب والمستخدم
        save_message_map(sent.message_id, user_id)

        # الأزرار مباشرة على الرسالة المحولة
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 بث للجميع", callback_data=f"broadcast:{user_id}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"ban:{user_id}")]
        ])
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=ADMIN_GROUP_ID,
                message_id=sent.message_id,
                reply_markup=keyboard
            )
        except:
            # ستيكر وفيديو دائري ما يقبل تعديل، نبعت رسالة صغيرة بالأزرار فقط
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=".",
                reply_markup=keyboard
            )

        # رد على المستخدم فقط بأول رسالة
        if first_time:
            await update.message.reply_text("✅ سنرد عليك في أقرب وقت ممكن.")
            mark_messaged(user_id)

    except Exception as e:
        logger.error(f"❌ خطأ: {e}", exc_info=True)


# ==================== ردود المشرفين ====================

async def handle_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == context.bot.id:
        return
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
    admin = update.effective_user
    admin_display = get_user_display(admin)

    try:
        if msg.text:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📨 رد من الإدارة:\n\n{msg.text}"
            )
        elif msg.photo:
            await context.bot.send_photo(
                chat_id=target_user_id,
                photo=msg.photo[-1].file_id,
                caption=f"📸 رد من الإدارة\n{msg.caption or ''}"
            )
        elif msg.voice:
            await context.bot.send_voice(
                chat_id=target_user_id,
                voice=msg.voice.file_id,
                caption="🎤 رد من الإدارة"
            )
        elif msg.video:
            await context.bot.send_video(
                chat_id=target_user_id,
                video=msg.video.file_id,
                caption=f"🎥 رد من الإدارة\n{msg.caption or ''}"
            )
        elif msg.audio:
            await context.bot.send_audio(
                chat_id=target_user_id,
                audio=msg.audio.file_id,
                caption=f"🎵 رد من الإدارة\n{msg.caption or ''}"
            )
        elif msg.document:
            await context.bot.send_document(
                chat_id=target_user_id,
                document=msg.document.file_id,
                caption=f"📎 رد من الإدارة\n{msg.caption or ''}"
            )
        elif msg.sticker:
            await context.bot.send_sticker(
                chat_id=target_user_id,
                sticker=msg.sticker.file_id
            )
        elif msg.video_note:
            await context.bot.send_video_note(
                chat_id=target_user_id,
                video_note=msg.video_note.file_id
            )
        else:
            await update.message.reply_text("❌ نوع الرد غير مدعوم")
            return

        await update.message.reply_text("✅ تم إرسال الرد!")

    except Exception as e:
        logger.error(f"❌ خطأ في الرد: {e}", exc_info=True)


# ==================== الأزرار ====================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_chat.id != ADMIN_GROUP_ID:
        return

    data = query.data

    if data.startswith("ban:"):
        user_id = int(data.split(":")[1])
        ban_user(user_id)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 بث للجميع", callback_data=f"broadcast:{user_id}")],
            [InlineKeyboardButton("✅ فك الحظر", callback_data=f"unban:{user_id}")]
        ]))
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"🚫 تم حظر `{user_id}`.", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=user_id, text="⛔ تم حظرك من استخدام البوت.")
        except: pass

    elif data.startswith("unban:"):
        user_id = int(data.split(":")[1])
        unban_user(user_id)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 بث للجميع", callback_data=f"broadcast:{user_id}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"ban:{user_id}")]
        ]))
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=f"✅ تم فك حظر `{user_id}`.", parse_mode="Markdown")
        try: await context.bot.send_message(chat_id=user_id, text="✅ تم فك حظرك، يمكنك التواصل مجدداً.")
        except: pass

    elif data.startswith("broadcast:"):
        r.set(f"{REDIS_PREFIX}:broadcast:{query.from_user.id}", "1", ex=300)
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text="📢 *وضع البث*\n\nأرسل الرسالة التي تريد بثها.\nأرسل /cancel للإلغاء.",
            parse_mode="Markdown"
        )


# ==================== أوامر ====================

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID and update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ استخدم: /ban user_id")
        return
    try:
        user_id = int(context.args[0])
        ban_user(user_id)
        await update.message.reply_text(f"🚫 تم حظر المستخدم {user_id}")
        try: await context.bot.send_message(chat_id=user_id, text="⛔ تم حظرك من استخدام البوت.")
        except: pass
    except ValueError:
        await update.message.reply_text("❌ ID غير صحيح.")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID and update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ استخدم: /unban user_id")
        return
    try:
        user_id = int(context.args[0])
        unban_user(user_id)
        await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم {user_id}")
        try: await context.bot.send_message(chat_id=user_id, text="✅ تم فك حظرك، يمكنك التواصل مجدداً.")
        except: pass
    except ValueError:
        await update.message.reply_text("❌ ID غير صحيح.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID and update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        f"📊 إحصائيات البوت:\n\n"
        f"👥 المستخدمين: {get_users_count()}\n"
        f"📨 الرسائل: {get_messages_count()}\n"
        f"🚫 المحظورين: {get_banned_count()}"
    )

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID and update.effective_user.id != OWNER_ID:
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("❌ لا يوجد مستخدمين للبث")
        return

    broadcast_text = " ".join(context.args) if context.args else None
    replied = update.message.reply_to_message

    if not broadcast_text and not replied:
        await update.message.reply_text("❌ استخدم:\n/bd نص الرسالة\nأو رد على رسالة بـ /bd")
        return

    status_msg = await update.message.reply_text(f"⏳ جاري البث لـ {len(users)} مستخدم...")
    success, failed = 0, 0

    for uid in users:
        try:
            if replied:
                if replied.text:
                    await context.bot.send_message(chat_id=int(uid), text=replied.text)
                elif replied.photo:
                    await context.bot.send_photo(chat_id=int(uid), photo=replied.photo[-1].file_id, caption=replied.caption)
                elif replied.video:
                    await context.bot.send_video(chat_id=int(uid), video=replied.video.file_id, caption=replied.caption)
                elif replied.voice:
                    await context.bot.send_voice(chat_id=int(uid), voice=replied.voice.file_id)
                elif replied.audio:
                    await context.bot.send_audio(chat_id=int(uid), audio=replied.audio.file_id, caption=replied.caption)
                elif replied.document:
                    await context.bot.send_document(chat_id=int(uid), document=replied.document.file_id, caption=replied.caption)
                elif replied.sticker:
                    await context.bot.send_sticker(chat_id=int(uid), sticker=replied.sticker.file_id)
                elif replied.animation:
                    await context.bot.send_animation(chat_id=int(uid), animation=replied.animation.file_id, caption=replied.caption)
                else:
                    await context.bot.send_message(chat_id=int(uid), text=broadcast_text or "")
            else:
                await context.bot.send_message(chat_id=int(uid), text=broadcast_text)
            success += 1
        except:
            failed += 1

    await status_msg.edit_text(
        f"✅ اكتمل البث!\n\n"
        f"✓ نجح: {success}\n"
        f"✗ فشل: {failed}"
    )

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return

    admin_id = update.effective_user.id

    # وضع البث
    if r.exists(f"{REDIS_PREFIX}:broadcast:{admin_id}"):
        if update.message.text == "/cancel":
            r.delete(f"{REDIS_PREFIX}:broadcast:{admin_id}")
            await update.message.reply_text("❌ تم إلغاء البث.")
            return
        r.delete(f"{REDIS_PREFIX}:broadcast:{admin_id}")
        users = get_all_users()
        status_msg = await update.message.reply_text(f"⏳ جاري البث لـ {len(users)} مستخدم...")
        success, failed = 0, 0
        for uid in users:
            try:
                await context.bot.send_message(chat_id=int(uid), text=update.message.text)
                success += 1
            except:
                failed += 1
        await status_msg.edit_text(f"✅ اكتمل البث!\n\n✓ نجح: {success}\n✗ فشل: {failed}")
        return

    # رد على مستخدم
    if update.message.reply_to_message:
        await handle_group_reply(update, context)


# ==================== التشغيل ====================

ALL_MESSAGES = (
    filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE |
    filters.AUDIO | filters.VIDEO_NOTE | filters.Sticker.ALL |
    filters.ANIMATION | filters.Document.ALL |
    filters.LOCATION | filters.CONTACT | filters.POLL
)

def main():
    try:
        r.ping()
        logger.info("✅ متصل بـ Redis Cloud!")
    except Exception as e:
        logger.error(f"❌ فشل الاتصال بـ Redis: {e}")
        return

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info("✅ Web server شغال على port 8080")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("bd", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # رسائل جروب الأدمن
    app.add_handler(MessageHandler(
        filters.Chat(ADMIN_GROUP_ID) & ALL_MESSAGES,
        handle_admin_text
    ))

    # رسائل المستخدمين الخاصة
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ALL_MESSAGES,
        handle_private_message
    ))

    logger.info("✅ البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

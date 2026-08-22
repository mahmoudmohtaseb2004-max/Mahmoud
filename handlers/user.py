from __future__ import annotations

import asyncio
import logging

from telegram import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from config import settings
from storage import Storage
from utils import MediaGroupCollector, escape_html

logger = logging.getLogger(__name__)


def _build_user_info_line(message: Message) -> str:
    user = message.from_user
    name = escape_html(user.first_name or "بدون اسم")
    username = f"@{user.username}" if user.username else "لا يوجد"
    return (
        f"📩 <b>رسالة جديدة</b>\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: {username}\n"
        f"🆔 chat_id: <code>{user.id}</code>\n"
        f"⬇️ الرسالة في الأسفل ⬇️"
    )


async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "مرحباً بك! 👋\n"
        "أرسل رسالتك (نص، صورة، فيديو، ملف، ألبوم، أو ملصق) هنا وسنقوم بتوجيهها للإدارة."
    )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or update.effective_chat.type != "private":
        return

    storage: Storage = context.bot_data["storage"]
    collector: MediaGroupCollector = context.bot_data["media_collector"]

    user_id = message.from_user.id

    if await storage.is_blocked(user_id):
        await message.reply_text("⛔ لا يمكنك إرسال رسائل حالياً.")
        return

    if await storage.is_temp_banned(user_id):
        remaining = await storage.get_temp_ban_remaining_seconds(user_id)
        minutes_left = max(1, remaining // 60)
        await message.reply_text(
            f"🚫 تم تقييدك مؤقتاً بسبب إرسال رسائل كثيرة. حاول بعد {minutes_left} دقيقة تقريباً."
        )
        return

    if await storage.is_flooding(user_id, settings.flood_window_seconds):
        return

    if await storage.check_rate_limit(user_id, settings.max_messages_per_minute):
        await storage.temp_ban(user_id, settings.temp_ban_minutes)
        await message.reply_text(
            f"🚫 تم تقييدك مؤقتاً لمدة {settings.temp_ban_minutes} دقيقة بسبب إرسال رسائل كثيرة جداً."
        )
        logger.warning("تم تطبيق حظر مؤقت على المستخدم %s بسبب تجاوز حد السبام.", user_id)
        return

    message_count = await storage.upsert_user(
        user_id, message.from_user.username, message.from_user.first_name
    )
    is_first_message = message_count == 1

    async def _process(messages: list[Message]) -> None:
        if len(messages) == 1:
            await _forward_single_message(messages[0], context, is_first_message)
        else:
            await _forward_album(messages, context, is_first_message)

    collector.add(message, _process)


async def _forward_single_message(
    message: Message, context: ContextTypes.DEFAULT_TYPE, is_first_message: bool
) -> None:
    storage: Storage = context.bot_data["storage"]
    user_id = message.from_user.id

    try:
        await context.bot.send_message(
            chat_id=settings.admin_group_id,
            text=_build_user_info_line(message),
            parse_mode=ParseMode.HTML,
        )
        copied = await context.bot.copy_message(
            chat_id=settings.admin_group_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await storage.save_mapping(copied.message_id, user_id)
        await storage.record_message()
        if is_first_message:
            await message.reply_text("✅ تم استلام رسالتك وإرسالها للإدارة بنجاح.")
        logger.info("تم توجيه رسالة من المستخدم %s بنجاح.", user_id)

    except Forbidden:
        logger.warning("لا يملك البوت صلاحية الإرسال لمجموعة الإدارة.")
    except RetryAfter as e:
        logger.warning("Rate limit من تليجرام، الانتظار %s ثانية وإعادة المحاولة...", e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await _forward_single_message(message, context, is_first_message)
        except TelegramError:
            await message.reply_text("⚠️ الخادم مشغول حالياً. حاول مرة أخرى بعد قليل.")
    except (TimedOut, NetworkError) as e:
        logger.error("مشكلة اتصال بالشبكة أثناء توجيه رسالة من %s: %s", user_id, e)
        await message.reply_text("⚠️ مشكلة اتصال مؤقتة، حاول مرة أخرى خلال لحظات.")
    except BadRequest as e:
        logger.error("طلب غير صالح أثناء توجيه رسالة من %s: %s", user_id, e)
        await message.reply_text("⚠️ تعذّر إرسال هذا النوع من الرسائل.")
    except TelegramError as e:
        logger.error("خطأ تليجرام أثناء توجيه رسالة من %s: %s", user_id, e)
        await message.reply_text("⚠️ حدث خطأ فني أثناء إرسال الرسالة. حاول لاحقاً.")
    except Exception:
        logger.exception("خطأ غير متوقع أثناء معالجة رسالة من %s", user_id)
        await message.reply_text("⚠️ حدث خطأ فني أثناء إرسال الرسالة. حاول لاحقاً.")


async def _forward_album(
    messages: list[Message], context: ContextTypes.DEFAULT_TYPE, is_first_message: bool
) -> None:
    storage: Storage = context.bot_data["storage"]
    first = messages[0]
    user_id = first.from_user.id

    try:
        await context.bot.send_message(
            chat_id=settings.admin_group_id,
            text=_build_user_info_line(first) + f"\n📦 ألبوم من {len(messages)} عنصر",
            parse_mode=ParseMode.HTML,
        )

        media_items = []
        for m in messages:
            if m.photo:
                media_items.append(InputMediaPhoto(m.photo[-1].file_id))
            elif m.video:
                media_items.append(InputMediaVideo(m.video.file_id))
            elif m.audio:
                media_items.append(InputMediaAudio(m.audio.file_id))
            elif m.document:
                media_items.append(InputMediaDocument(m.document.file_id))

        if not media_items:
            return

        sent_messages = await context.bot.send_media_group(
            chat_id=settings.admin_group_id, media=media_items
        )

        for sent in sent_messages:
            await storage.save_mapping(sent.message_id, user_id)

        await storage.record_message()
        if is_first_message:
            await first.reply_text("✅ تم استلام الألبوم وإرساله للإدارة بنجاح.")
        logger.info("تم توجيه ألبوم من %s عنصر من المستخدم %s.", len(messages), user_id)

    except TelegramError as e:
        logger.error("خطأ أثناء توجيه ألبوم من %s: %s", user_id, e)
        await first.reply_text("⚠️ حدث خطأ أثناء إرسال الألبوم. حاول لاحقاً.")

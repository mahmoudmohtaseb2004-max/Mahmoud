from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from config import settings
from permissions import is_group_admin
from storage import Storage

logger = logging.getLogger(__name__)


def _is_admin_group(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.id == settings.admin_group_id


async def _require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if not _is_admin_group(update) or message is None:
        return False

    user = update.effective_user
    if user is None or not await is_group_admin(context, user.id):
        await message.reply_text("⛔ هذا الأمر متاح لأدمنية المجموعة فقط.")
        logger.info(
            "محاولة استخدام أمر إداري من مستخدم غير مخوّل: %s",
            user.id if user else "unknown",
        )
        return False

    return True


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return

    message = update.effective_message
    if message.reply_to_message is None:
        return

    storage: Storage = context.bot_data["storage"]
    target_user_id = await storage.get_user_for_admin_message(message.reply_to_message.message_id)

    if not target_user_id:
        await message.reply_text("⚠️ لم أستطع إيجاد المستخدم المرتبط بهذه الرسالة (ربما قديمة جداً).")
        return

    try:
        await context.bot.send_message(target_user_id, "📨 <b>رد من الإدارة:</b>", parse_mode="HTML")
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await message.reply_text("✅ تم إرسال الرد للمستخدم.")
        logger.info("تم إرسال رد الأدمن إلى المستخدم %s.", target_user_id)
    except Forbidden:
        await message.reply_text("⚠️ فشل الإرسال: المستخدم حظر البوت.")
    except RetryAfter as e:
        logger.warning("Rate limit أثناء رد الأدمن، الانتظار %s ثانية.", e.retry_after)
        await asyncio.sleep(e.retry_after)
        await message.reply_text("⚠️ الخادم كان مشغولاً، أعد المحاولة من فضلك.")
    except (TimedOut, NetworkError):
        await message.reply_text("⚠️ مشكلة اتصال مؤقتة، أعد المحاولة خلال لحظات.")
    except TelegramError as e:
        logger.error("فشل إرسال رد الأدمن إلى %s: %s", target_user_id, e)
        await message.reply_text("⚠️ فشل إرسال الرد.")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_ban_state(update, context, blocked=True)


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_ban_state(update, context, blocked=False)


async def _set_ban_state(update: Update, context: ContextTypes.DEFAULT_TYPE, *, blocked: bool) -> None:
    if not await _require_admin(update, context):
        return

    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("استخدم هذا الأمر بالرد (Reply) على رسالة المستخدم.")
        return

    storage: Storage = context.bot_data["storage"]
    target_user_id = await storage.get_user_for_admin_message(message.reply_to_message.message_id)
    if not target_user_id:
        await message.reply_text("⚠️ لم أستطع تحديد المستخدم المرتبط بهذه الرسالة.")
        return

    await storage.set_blocked(target_user_id, blocked)
    status = "تم حظره 🚫" if blocked else "تم فك حظره ✅"
    await message.reply_text(f"المستخدم <code>{target_user_id}</code>: {status}", parse_mode="HTML")

    notice = (
        "⛔ تم حظرك من استخدام هذا البوت من قبل الإدارة."
        if blocked
        else "✅ تم فك الحظر عنك، يمكنك إرسال رسائلك الآن."
    )
    try:
        await context.bot.send_message(target_user_id, notice)
    except Forbidden:
        pass


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return

    storage: Storage = context.bot_data["storage"]
    stats = await storage.get_stats()
    text = (
        "📊 <b>إحصائيات البوت</b>\n"
        f"• إجمالي الرسائل: {stats['messages_total']}\n"
        f"• رسائل اليوم: {stats['messages_today']}\n"
        f"• عدد المستخدمين: {stats['known_users']}\n"
        f"• عدد المحظورين دائماً: {stats['blocked_users']}\n"
        f"• عدد المقيّدين مؤقتاً الآن: {stats['temp_banned_users']}"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return

    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text("استخدم /broadcast بالرد على الرسالة التي تريد بثها.")
        return

    storage: Storage = context.bot_data["storage"]
    users = await storage.get_all_users()
    await message.reply_text(f"🚀 جاري البث إلى {len(users)} مستخدم...")

    sent, failed = 0, 0
    for user_id in users:
        try:
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat_id,
                message_id=message.reply_to_message.message_id,
            )
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat_id,
                    message_id=message.reply_to_message.message_id,
                )
                sent += 1
            except TelegramError:
                failed += 1
        except (Forbidden, BadRequest, TimedOut, NetworkError):
            failed += 1
        except TelegramError as e:
            logger.error("خطأ غير متوقع أثناء البث للمستخدم %s: %s", user_id, e)
            failed += 1
        await asyncio.sleep(0.05)

    await message.reply_text(f"✅ تم البث: {sent} نجحت، {failed} فشلت.")

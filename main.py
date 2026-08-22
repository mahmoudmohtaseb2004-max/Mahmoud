"""
Admin Inbox Bot v2 (نسخة متوافقة مع Render)
=============================================
بالإضافة لتشغيل البوت، نشغّل سيرفر ويب بسيط (aiohttp) جنبه.
السبب: خطة Render المجانية بتدعم "Web Service" بس (بيستقبل طلبات HTTP)،
مش "Background Worker" (المخصص للبوتات، ومدفوع). فبنخلي Render يشوف
تطبيقنا كـ Web Service عادي، وبنستخدم خدمة مجانية (UptimeRobot) تبعتله
طلب كل كام دقيقة عشان يفضل صاحي وما يدخلش في "وضع النوم" بعد 15 دقيقة
من عدم النشاط.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import settings
from handlers import admin, user
from logging_setup import setup_logging
from storage import Storage
from utils import MediaGroupCollector

setup_logging(settings.log_level)
logger = logging.getLogger("admin_inbox_bot")


async def _post_init(application: Application) -> None:
    storage: Storage = application.bot_data["storage"]
    await storage.ping()
    logger.info("✅ الاتصال بـ Redis ناجح.")
    me = await application.bot.get_me()
    logger.info("🚀 البوت @%s يعمل الآن ومستعد لاستقبال الرسائل...", me.username)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("استثناء غير متوقع أثناء معالجة تحديث: %s", context.error, exc_info=context.error)


async def _cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    max_age_seconds = settings.mapping_max_age_days * 24 * 60 * 60
    removed = await storage.cleanup_old_mappings(max_age_seconds)
    if removed:
        logger.info("🧹 تم تنظيف %s رابط رسالة قديم من قاعدة البيانات.", removed)


def build_application() -> Application:
    application = Application.builder().token(settings.bot_token).build()

    application.bot_data["storage"] = Storage(settings.redis_url)
    application.bot_data["media_collector"] = MediaGroupCollector(
        settings.media_group_flush_delay
    )

    private_chat = filters.ChatType.PRIVATE
    admin_group = filters.Chat(chat_id=settings.admin_group_id)

    application.add_handler(CommandHandler(["start", "help"], user.send_welcome, filters=private_chat))
    application.add_handler(
        MessageHandler(
            private_chat
            & (
                filters.TEXT
                | filters.PHOTO
                | filters.VIDEO
                | filters.Document.ALL
                | filters.AUDIO
                | filters.VOICE
                | filters.Sticker.ALL
                | filters.VIDEO_NOTE
                | filters.LOCATION
                | filters.CONTACT
            )
            & ~filters.COMMAND,
            user.handle_user_message,
        )
    )

    application.add_handler(CommandHandler("ban", admin.ban_command, filters=admin_group))
    application.add_handler(CommandHandler("unban", admin.unban_command, filters=admin_group))
    application.add_handler(CommandHandler("stats", admin.stats_command, filters=admin_group))
    application.add_handler(CommandHandler("broadcast", admin.broadcast_command, filters=admin_group))
    application.add_handler(
        MessageHandler(admin_group & filters.REPLY & ~filters.COMMAND, admin.handle_admin_reply)
    )

    application.add_error_handler(_on_error)

    if application.job_queue is not None:
        application.job_queue.run_repeating(
            _cleanup_job,
            interval=settings.cleanup_interval_seconds,
            first=60,
            name="cleanup_old_mappings",
        )

    return application


async def _run_keepalive_server() -> web.AppRunner:
    """سيرفر ويب بسيط بيرد 200 OK على أي طلب - هذا كل اللي محتاجه Render وUptimeRobot."""

    async def handle_ping(request: web.Request) -> web.Response:
        return web.Response(text="✅ Bot is alive")

    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.port)
    await site.start()
    logger.info("🌐 سيرفر keep-alive شغال على المنفذ %s", settings.port)
    return runner


async def main() -> None:
    application = build_application()

    await application.initialize()
    await _post_init(application)
    await application.start()
    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
    )

    web_runner = await _run_keepalive_server()

    stop_event = asyncio.Event()

    def _request_stop(*_args: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # بعض الأنظمة (زي ويندوز) ما بتدعم add_signal_handler بنفس الطريقة
            pass

    logger.info("البوت جاهز بالكامل، بانتظار إشارة الإيقاف (Ctrl+C أو SIGTERM)...")
    await stop_event.wait()

    logger.info("🛑 إشارة إيقاف مستلمة، جاري الإغلاق الآمن...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    await web_runner.cleanup()

    storage: Storage = application.bot_data["storage"]
    await storage.close()
    logger.info("تم الإغلاق بنجاح.")


if __name__ == "__main__":
    asyncio.run(main())

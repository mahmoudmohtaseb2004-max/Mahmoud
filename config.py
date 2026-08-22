from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"⚠️ متغير البيئة المطلوب مفقود: {name} (راجع ملف .env)")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_group_id: int
    redis_url: str
    flood_window_seconds: float
    max_messages_per_minute: int
    temp_ban_minutes: int
    admin_cache_ttl_seconds: int
    mapping_max_age_days: int
    cleanup_interval_seconds: int
    media_group_flush_delay: float
    log_level: str
    port: int


def load_settings() -> Settings:
    token = _require("BOT_TOKEN")

    try:
        admin_group_id = int(_require("ADMIN_GROUP_ID"))
    except ValueError:
        raise SystemExit("⚠️ ADMIN_GROUP_ID يجب أن يكون رقماً صحيحاً، مثال: -1001234567890")

    return Settings(
        bot_token=token,
        admin_group_id=admin_group_id,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        flood_window_seconds=float(os.getenv("FLOOD_WINDOW_SECONDS", "2.5")),
        max_messages_per_minute=int(os.getenv("MAX_MESSAGES_PER_MINUTE", "5")),
        temp_ban_minutes=int(os.getenv("TEMP_BAN_MINUTES", "10")),
        admin_cache_ttl_seconds=int(os.getenv("ADMIN_CACHE_TTL_SECONDS", "300")),
        mapping_max_age_days=int(os.getenv("MAPPING_MAX_AGE_DAYS", "7")),
        cleanup_interval_seconds=int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600")),
        media_group_flush_delay=float(os.getenv("MEDIA_GROUP_FLUSH_DELAY", "1.2")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        # Render بيحدد رقم البورت تلقائياً عبر متغير PORT وقت التشغيل
        port=int(os.getenv("PORT", "10000")),
    )


settings = load_settings()

from __future__ import annotations

import logging
import time

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import settings

logger = logging.getLogger(__name__)

_ADMIN_STATUSES = {"administrator", "creator"}

_cache: dict[int, tuple[bool, float]] = {}


async def is_group_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    now = time.time()
    cached = _cache.get(user_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    try:
        member = await context.bot.get_chat_member(settings.admin_group_id, user_id)
        result = member.status in _ADMIN_STATUSES
    except TelegramError as e:
        logger.warning("تعذّر التحقق من صلاحية المستخدم %s: %s", user_id, e)
        result = False

    _cache[user_id] = (result, now + settings.admin_cache_ttl_seconds)
    return result


def invalidate(user_id: int) -> None:
    _cache.pop(user_id, None)

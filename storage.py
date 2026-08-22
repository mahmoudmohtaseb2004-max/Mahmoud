"""
طبقة التخزين (Redis)
=====================
تعمل مع أي Redis عادي (Docker محلي)، أو مع Upstash عبر رابط rediss:// (TLS).

المفاتيح المستخدمة:
    map:{admin_message_id}      -> user_id  (TTL أسبوع)
    map_index                   -> sorted set زمني لتنظيف الروابط القديمة
    blocked                     -> set من user_id المحظورين دائماً
    tempban:{user_id}           -> حظر مؤقت (TTL دقائق)
    temp_banned_index           -> فهرس للحظر المؤقت النشط
    known_users                 -> set من كل user_id اللي تفاعلوا مع البوت
    user:{user_id}              -> hash فيه بيانات المستخدم الكاملة
    flood:{user_id}             -> عداد قصير المدى لمنع السبام الفوري
    rate:{user_id}:{minute}     -> عداد لكل دقيقة لمنع الإغراق
    stats:messages_total        -> عداد كلي
    stats:messages:{YYYY-MM-DD} -> عداد يومي
    stats:blocked_total         -> عداد المحظورين التراكمي
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import redis.asyncio as redis

_MAPPING_TTL_SECONDS = 7 * 24 * 60 * 60  # أسبوع كافي لأي رد متأخر من الأدمن


class Storage:
    def __init__(self, redis_url: str) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> bool:
        return await self._redis.ping()

    # -- ربط رسائل الأدمن بالمستخدمين ------------------------------------

    async def save_mapping(self, admin_message_id: int, user_id: int) -> None:
        async with self._redis.pipeline() as pipe:
            pipe.set(f"map:{admin_message_id}", user_id, ex=_MAPPING_TTL_SECONDS)
            pipe.zadd("map_index", {str(admin_message_id): time.time()})
            await pipe.execute()

    async def get_user_for_admin_message(self, admin_message_id: int) -> int | None:
        value = await self._redis.get(f"map:{admin_message_id}")
        return int(value) if value else None

    async def cleanup_old_mappings(self, max_age_seconds: int) -> int:
        threshold = time.time() - max_age_seconds
        old_ids = await self._redis.zrangebyscore("map_index", 0, threshold)
        if not old_ids:
            return 0

        async with self._redis.pipeline() as pipe:
            for admin_message_id in old_ids:
                pipe.delete(f"map:{admin_message_id}")
            pipe.zremrangebyscore("map_index", 0, threshold)
            await pipe.execute()

        return len(old_ids)

    # -- الحظر الدائم -------------------------------------------------------

    async def is_blocked(self, user_id: int) -> bool:
        return bool(await self._redis.sismember("blocked", user_id))

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        if blocked:
            await self._redis.sadd("blocked", user_id)
            await self._redis.incr("stats:blocked_total")
        else:
            await self._redis.srem("blocked", user_id)

    async def count_blocked_users(self) -> int:
        return await self._redis.scard("blocked")

    # -- الحظر المؤقت (نتيجة تجاوز حد السبام) --------------------------------

    async def temp_ban(self, user_id: int, minutes: int) -> None:
        await self._redis.set(f"tempban:{user_id}", "1", ex=minutes * 60)
        await self._redis.sadd("temp_banned_index", user_id)

    async def is_temp_banned(self, user_id: int) -> bool:
        return await self._redis.exists(f"tempban:{user_id}") == 1

    async def get_temp_ban_remaining_seconds(self, user_id: int) -> int:
        ttl = await self._redis.ttl(f"tempban:{user_id}")
        return max(ttl, 0)

    async def count_temp_banned(self) -> int:
        ids = await self._redis.smembers("temp_banned_index")
        active, stale = 0, []
        for uid in ids:
            ttl = await self._redis.ttl(f"tempban:{uid}")
            if ttl and ttl > 0:
                active += 1
            else:
                stale.append(uid)
        if stale:
            await self._redis.srem("temp_banned_index", *stale)
        return active

    # -- المستخدمون: جدول كامل + فهرس للبرودكاست --------------------------

    async def upsert_user(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> int:
        """يحدّث بيانات المستخدم ويرجع عدد رسائله الإجمالي بعد هذه الرسالة."""
        now = time.time()
        key = f"user:{user_id}"
        async with self._redis.pipeline() as pipe:
            pipe.sadd("known_users", user_id)
            pipe.hsetnx(key, "joined_at", now)
            pipe.hset(
                key,
                mapping={
                    "username": username or "",
                    "first_name": first_name or "",
                    "last_active": now,
                },
            )
            pipe.hincrby(key, "message_count", 1)
            results = await pipe.execute()

        return results[-1]

    async def get_user_info(self, user_id: int) -> dict:
        return await self._redis.hgetall(f"user:{user_id}")

    async def get_all_users(self) -> list[int]:
        members = await self._redis.smembers("known_users")
        return [int(m) for m in members]

    async def count_known_users(self) -> int:
        return await self._redis.scard("known_users")

    # -- حماية السبام -------------------------------------------------------

    async def is_flooding(self, user_id: int, window_seconds: float) -> bool:
        key = f"flood:{user_id}"
        was_set = await self._redis.set(key, "1", ex=max(1, int(window_seconds)), nx=True)
        return not was_set

    async def check_rate_limit(self, user_id: int, max_per_minute: int) -> bool:
        minute_bucket = int(time.time() // 60)
        key = f"rate:{user_id}:{minute_bucket}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 65)
        return count > max_per_minute

    # -- إحصائيات -----------------------------------------------------------

    async def record_message(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self._redis.pipeline() as pipe:
            pipe.incr("stats:messages_total")
            pipe.incr(f"stats:messages:{today}")
            pipe.expire(f"stats:messages:{today}", 60 * 60 * 24 * 90)
            await pipe.execute()

    async def get_stats(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = await self._redis.get("stats:messages_total") or "0"
        today_count = await self._redis.get(f"stats:messages:{today}") or "0"
        return {
            "messages_total": int(total),
            "messages_today": int(today_count),
            "known_users": await self.count_known_users(),
            "blocked_users": await self.count_blocked_users(),
            "temp_banned_users": await self.count_temp_banned(),
        }

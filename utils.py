from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from telegram import Message

logger = logging.getLogger(__name__)


def escape_html(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class _AlbumBuffer:
    messages: list[Message] = field(default_factory=list)
    flush_task: asyncio.Task | None = None


class MediaGroupCollector:
    def __init__(self, flush_delay: float) -> None:
        self._flush_delay = flush_delay
        self._buffers: dict[str, _AlbumBuffer] = {}

    def add(self, message: Message, on_ready) -> None:
        group_id = message.media_group_id
        if group_id is None:
            asyncio.create_task(on_ready([message]))
            return

        buffer = self._buffers.setdefault(group_id, _AlbumBuffer())
        buffer.messages.append(message)

        if buffer.flush_task:
            buffer.flush_task.cancel()

        async def _flush() -> None:
            try:
                await asyncio.sleep(self._flush_delay)
            except asyncio.CancelledError:
                return
            finished = self._buffers.pop(group_id, None)
            if finished:
                ordered = sorted(finished.messages, key=lambda m: m.message_id)
                await on_ready(ordered)

        buffer.flush_task = asyncio.create_task(_flush())

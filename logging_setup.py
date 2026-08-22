from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


def setup_logging(level: str = "INFO") -> None:
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console_handler)

    try:
        file_handler = RotatingFileHandler(
            "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # بعض المنصات السحابية (زي Render) عندها نظام ملفات للقراءة فقط
        # جزئياً؛ اللوج على الشاشة (stdout) كافي هناك ويظهر في لوحة التحكم.
        pass

    logging.getLogger("httpx").setLevel(logging.WARNING)

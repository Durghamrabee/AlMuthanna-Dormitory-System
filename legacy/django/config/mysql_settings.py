"""Optional legacy MySQL configuration. Never selected by the local application."""
import os
from .settings import *  # noqa: F403

DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql",
    "NAME": os.getenv("DB_NAME", "almuthanna_dormitory"),
    "USER": os.getenv("DB_USER", "almuthanna_app"),
    "PASSWORD": os.getenv("DB_PASSWORD", ""),
    "HOST": os.getenv("DB_HOST", "127.0.0.1"),
    "PORT": os.getenv("DB_PORT", "3306"),
    "OPTIONS": {"charset": "utf8mb4", "isolation_level": "read committed",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES', default_storage_engine=INNODB"},
}}

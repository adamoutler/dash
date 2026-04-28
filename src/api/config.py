import os
import json
import logging
from filelock import FileLock

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "data")
LOGS_DIR = os.getenv("LOGS_DIR", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)


class ConfigManager:
    def __init__(self, filepath=os.path.join(DATA_DIR, "settings.json")):
        self.filepath = filepath
        self.lockpath = f"{filepath}.lock"
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                json.dump({}, f)

    def get_settings(self) -> dict:
        lock = FileLock(self.lockpath)
        try:
            with lock.acquire(timeout=5):
                if not os.path.exists(self.filepath):
                    return {}
                with open(self.filepath, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read settings: {e}")
            return {}

    def update_settings(self, updates: dict):
        lock = FileLock(self.lockpath)
        try:
            with lock.acquire(timeout=5):
                settings = {}
                if os.path.exists(self.filepath):
                    with open(self.filepath, "r") as f:
                        settings = json.load(f)

                for k, v in updates.items():
                    if v is not None and v != "":
                        settings[k] = v

                with open(self.filepath, "w") as f:
                    json.dump(settings, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            raise e

    def get_value(self, json_key: str, env_key: str = None) -> str:
        settings = self.get_settings()
        if json_key in settings and settings[json_key]:
            return settings[json_key]
        if env_key:
            return os.environ.get(env_key, "")
        return ""

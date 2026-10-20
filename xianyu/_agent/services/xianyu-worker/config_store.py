from __future__ import annotations

import json
import os
from pathlib import Path


class ConfigStore:
    def __init__(self, path: str | Path = "data/settings.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, updates: dict) -> dict:
        current = self.load()
        current.update({k: v for k, v in updates.items() if v is not None})
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return current

    @staticmethod
    def apply_environment(config: dict):
        mapping = {
            "cookie": "COOKIES_STR",
            "api_key": "API_KEY",
            "model_base_url": "MODEL_BASE_URL",
            "model_name": "MODEL_NAME",
        }
        for key, env_name in mapping.items():
            if config.get(key):
                os.environ[env_name] = str(config[key])

    @staticmethod
    def masked(config: dict) -> dict:
        result = {k: v for k, v in config.items() if k not in {"cookie", "api_key"} and not k.startswith("embedding_")}
        result["cookie_configured"] = bool(config.get("cookie"))
        result["api_key_configured"] = bool(config.get("api_key"))
        return result

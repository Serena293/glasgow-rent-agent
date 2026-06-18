from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv_if_available()
    config_path = Path(path or os.getenv("HOUSE_AGENT_CONFIG", "config.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required. Run: python -m pip install -e .") from exc
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    apply_env_overrides(config)
    return config


def apply_env_overrides(config: dict[str, Any]) -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        config.setdefault("app", {})["database_url"] = database_url
    db_path = os.getenv("HOUSE_AGENT_DB_PATH")
    if db_path and not database_url:
        config.setdefault("app", {})["database_url"] = f"sqlite:///{db_path}"
    baseline_on_empty = os.getenv("HOUSE_AGENT_BASELINE_ON_EMPTY_DB")
    if baseline_on_empty is not None:
        config.setdefault("runtime", {})["baseline_on_empty_db"] = baseline_on_empty.lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    credentials = os.getenv("GOOGLE_CREDENTIALS_FILE")
    if credentials:
        config.setdefault("email", {})["credentials_file"] = credentials
    token = os.getenv("GOOGLE_TOKEN_FILE")
    if token:
        config.setdefault("email", {})["token_file"] = token


def project_path(config_path: str | Path | None, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    base = Path(config_path or os.getenv("HOUSE_AGENT_CONFIG", "config.yaml")).resolve().parent
    return base / path

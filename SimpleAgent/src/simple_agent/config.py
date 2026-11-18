"""Configuration is local to the directory from which the app is launched."""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    model: str
    base_url: str | None
    api_key: str
    skill_dirs: list[Path]
    mcp_servers: dict
    script_approval: bool = False
    script_timeout: float = 60
    script_output_limit: int = 32768


def load_config(path: Path = Path("config.json")) -> Config:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object")
    servers = data.get("mcpServers", {})
    dirs = data.get("skillDirs", [".agents/skills", "skills"])
    if not isinstance(servers, dict) or not isinstance(dirs, list) or not all(isinstance(p, str) for p in dirs):
        raise ValueError("mcpServers must be an object and skillDirs must be a list of paths")
    approval = data.get("scriptApproval", False)
    timeout = data.get("scriptTimeout", 60)
    output_limit = data.get("scriptOutputLimit", 32768)
    api_key = data.get("apiKey", "")
    if not isinstance(api_key, str):
        raise ValueError("apiKey must be a string")
    if not isinstance(approval, bool):
        raise ValueError("scriptApproval must be true or false")
    try:
        valid_timeout = not isinstance(timeout, bool) and isinstance(timeout, (int, float)) and math.isfinite(timeout) and timeout > 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError("scriptTimeout must be a positive finite number of seconds")
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit <= 0:
        raise ValueError("scriptOutputLimit must be a positive integer number of bytes")
    return Config(
        model=os.getenv("OPENAI_MODEL") or data.get("model", "gpt-4.1-mini"),
        base_url=os.getenv("OPENAI_BASE_URL") or data.get("baseUrl"),
        api_key=os.getenv("OPENAI_API_KEY") or api_key,
        skill_dirs=[Path(p).expanduser() for p in dirs],
        mcp_servers=servers,
        script_approval=approval,
        script_timeout=timeout,
        script_output_limit=output_limit,
    )

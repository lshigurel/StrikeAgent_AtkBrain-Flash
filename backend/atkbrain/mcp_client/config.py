"""Validated, revisioned configuration. No network I/O in the store."""
from __future__ import annotations
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROLES = frozenset({"recon", "web-exploit"})

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ToolRule(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    roles: list[str] = Field(default_factory=lambda: sorted(ROLES))
    profile: Literal["pure", "http_url"] = "pure"
    target_pointers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rule(self):
        if not self.roles or not set(self.roles) <= ROLES:
            raise ValueError("roles must be recon or web-exploit")
        if self.profile == "http_url" and not self.target_pointers:
            raise ValueError("http_url requires target_pointers")
        if any(not p.startswith("/") or "*" in p for p in self.target_pointers):
            raise ValueError("target_pointers must be concrete JSON Pointers")
        return self

class ServerFields(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    enabled: bool = False
    transport: Literal["stdio", "streamable_http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: str = ""
    url: str = ""
    allowed_tools: list[ToolRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_transport(self):
        if len({r.name for r in self.allowed_tools}) != len(self.allowed_tools):
            raise ValueError("duplicate tool rules")
        if self.transport == "stdio":
            if not Path(self.command).is_absolute() or not Path(self.cwd).is_absolute():
                raise ValueError("stdio command and cwd must be absolute Linux paths")
            if self.url:
                raise ValueError("stdio cannot have a URL")
        else:
            u = urlsplit(self.url)
            if not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError("URL must have a host and no credentials, query or fragment")
            if u.scheme != "https" and not (u.scheme == "http" and u.hostname in {"localhost","127.0.0.1","::1"}):
                raise ValueError("HTTP is only allowed on loopback; otherwise use HTTPS")
            if self.command or self.args or self.cwd:
                raise ValueError("HTTP cannot have stdio fields")
        return self

class ServerConfig(ServerFields):
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

class ServerConfigPatch(ServerFields):
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_secrets(self):
        for name in ("env", "headers"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError("omit secrets to preserve them; use {} to clear")
        return self

class McpConfig(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    servers: list[ServerConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.servers}) != len(self.servers):
            raise ValueError("duplicate server IDs")
        return self

class ConfigConflict(ValueError):
    pass

class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> McpConfig:
        with self._lock:
            if not self.path.exists():
                return McpConfig()
            return McpConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def get(self, server_id: str) -> ServerConfig:
        for server in self.load().servers:
            if server.id == server_id:
                return server
        raise KeyError(server_id)

    def public_config(self) -> dict:
        config = self.load()
        out = config.model_dump()
        for item, server in zip(out["servers"], config.servers):
            item.pop("env")
            item.pop("headers")
            item["env_keys"] = sorted(server.env)
            item["header_keys"] = sorted(server.headers)
        return out

    def save(self, patches: list[ServerConfigPatch], expected_revision: int) -> McpConfig:
        with self._lock:
            previous = self.load()
            if previous.revision != expected_revision:
                raise ConfigConflict("configuration changed; reload before saving")
            old = {s.id:s for s in previous.servers}
            servers = []
            for patch in patches:
                data = patch.model_dump(exclude={"env","headers"})
                for field in ("env", "headers"):
                    data[field] = (getattr(patch, field) if field in patch.model_fields_set
                                   else getattr(old[patch.id], field) if patch.id in old else {})
                servers.append(ServerConfig.model_validate(data))
            config = McpConfig(revision=previous.revision+1, servers=servers)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.parent.chmod(0o700)
            fd, temp = tempfile.mkstemp(prefix=".mcp-", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(config.model_dump_json(indent=2))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return config


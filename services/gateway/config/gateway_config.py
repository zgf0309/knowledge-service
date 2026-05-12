# -*- coding: utf-8 -*-
"""API Gateway 配置读取。

精简版原则：配置优先从 gateway_config.yaml 读取；如果文件不存在，使用
knowledge-web 当前需要的最小默认配置。
"""
import os
import re
from pathlib import Path
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class ServiceConfig:
    name: str = ""
    host: str = "localhost"
    port: int = 8000
    prefix: str = ""
    health_check: str = "/health"
    timeout: int = 5
    max_retries: int = 3


@dataclass
class RouteRule:
    path: str = ""
    service: str = ""
    methods: list[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE"])
    rate_limit: int | None = None
    auth_required: bool = True
    strip_prefix: bool = False

class GatewayConfig:
    """网关配置管理器（单例）。"""

    _instance = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._config:
            self._load_config()

    def _load_config(self) -> None:
        config_file = os.getenv("GATEWAY_CONFIG", "gateway_config.yaml")
        possible_paths = [
            Path(config_file), Path(__file__).parent.parent / config_file, Path(__file__).parent.parent.parent / config_file, ]
        for path in possible_paths:
            if path.exists():
                if yaml is None:
                    self._config = self._default_config()
                    print("⚠️  未安装 PyYAML，跳过 gateway_config.yaml，使用精简默认配置")
                    return
                with open(path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
                print(f"✅ 加载网关配置：{path.resolve()}")
                return

        self._config = self._default_config()
        print("⚠️  gateway_config.yaml 不存在，使用精简默认配置")

    @staticmethod
    def _default_config() -> dict:
        return {
            "services": [
                {"name": "knowledge-service", "host": "localhost", "port": 7101, "prefix": "/ai/knowledge"}, {"name": "file_service", "host": "localhost", "port": 7103, "prefix": "/ai/files"}, {"name": "model_service", "host": "localhost", "port": 7104, "prefix": "/ai/model"}, {"name": "chat_service", "host": "localhost", "port": 7105, "prefix": "/chat"}, {"name": "parser_service", "host": "localhost", "port": 7106, "prefix": "/ai/knowledge/doc/chunk"}, ], "routes": [
                {"path": "/ai/knowledge/doc/chunk*", "service": "parser_service"}, {"path": "/ai/knowledge/mdcontent", "methods": ["GET"], "service": "file_service"}, {"path": "/ai/files/*", "methods": ["GET", "POST", "DELETE"], "service": "file_service"}, {"path": "/ai/embedding/*", "methods": ["GET"], "service": "model_service", "auth_required": False}, {"path": "/chat/*", "methods": ["GET", "POST", "DELETE"], "service": "chat_service"}, {"path": "/ai/knowledge*", "service": "knowledge-service"}, ], "auth": {"exclude_paths": ["/health", "/metrics", "/api/v1/auth/sso/login", "/api/v1/auth/sso/callback"]}, "rate_limit": {"enabled": True, "default_limit": 100, "burst": 200}, "circuit_breaker": {"enabled": True, "failure_threshold": 5, "recovery_timeout": 30, "timeout_seconds": 30}, }

    @property
    def services(self) -> list[ServiceConfig]:
        return [ServiceConfig(**s) for s in self._config.get("services", [])]

    @property
    def routes(self) -> list[RouteRule]:
        return [RouteRule(**r) for r in self._config.get("routes", [])]

    @property
    def auth_config(self) -> dict:
        return self._config.get("auth", {})

    @property
    def rate_limit_config(self) -> dict:
        return self._config.get("rate_limit", {})

    @property
    def circuit_breaker_config(self) -> dict:
        return self._config.get("circuit_breaker", {})

    def get_service_by_name(self, name: str) -> ServiceConfig | None:
        return next((service for service in self.services if service.name == name), None)

    def match_route(self, path: str, method: str) -> RouteRule | None:
        """按顺序匹配路由，配置文件中越靠前优先级越高。"""
        for route in self.routes:
            if method not in route.methods:
                continue
            pattern = route.path.replace("*", ".*")
            if re.match(f"^{pattern}$", path):
                return route
        return None

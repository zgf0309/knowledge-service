# -*- coding: utf-8 -*-
"""
纯 ASGI 网关中间件（不缓冲 StreamingResponse）

替换所有 BaseHTTPMiddleware，解决 SSE 流式响应被缓冲的问题。
BaseHTTPMiddleware 的 call_next() 内部使用队列缓冲 response body，
导致 SSE 事件帧全部被收集后才一次性发送给客户端。

本中间件直接操作 ASGI send/receive，response body 逐 chunk 透传，
确保 SSE 事件帧实时到达前端。
"""
import time
import json
import logging
import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable

import jwt

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

from config.gateway_config import GatewayConfig
from middleware.rate_limit import TokenBucket
from middleware.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

class StreamingGatewayMiddleware:
    """
    纯 ASGI 中间件，整合 logging / auth / rate_limit / circuit_breaker / metrics。
    不使用 BaseHTTPMiddleware，确保 StreamingResponse 的 body chunk 实时透传。
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self.config = GatewayConfig()

        # Auth 配置
        auth_cfg = self.config.auth_config
        self.jwt_secret = auth_cfg.get("jwt_secret", "your-secret-key")
        self.jwt_algorithm = auth_cfg.get("jwt_algorithm", "HS256")
        self.exclude_paths = set(auth_cfg.get("exclude_paths", []))

        # Rate limit 配置
        rate_cfg = self.config.rate_limit_config
        self.rate_limit_enabled = rate_cfg.get("enabled", True)
        self.default_limit = rate_cfg.get("default_limit", 100)
        self.burst = rate_cfg.get("burst", 200)
        self.buckets = defaultdict(lambda: TokenBucket(self.default_limit, self.burst))

        # Circuit breaker 配置
        cb_cfg = self.config.circuit_breaker_config
        self.cb_enabled = cb_cfg.get("enabled", True)
        self.failure_threshold = cb_cfg.get("failure_threshold", 5)
        self.recovery_timeout = cb_cfg.get("recovery_timeout", 30)
        self.breakers = defaultdict(
            lambda: CircuitBreaker(self.failure_threshold, self.recovery_timeout)
        )

        logger.info("StreamingGatewayMiddleware initialized (non-buffering ASGI)")

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        path = scope.get("path", "/")
        method = scope.get("method", "GET")
        client_host = "unknown"
        if scope.get("client"):
            client_host = scope["client"][0]

        # === 请求日志 ===
        query_string = scope.get("query_string", b"").decode("utf-8", errors="replace")
        logger.info(f"📥 请求 | {client_host} | {method} {path} | qs: {query_string}")

        # === 认证检查 ===
        auth_error = self._check_auth(scope, path)
        if auth_error:
            await self._send_json_error(send, auth_error["status"], auth_error["detail"])
            return

        # === 限流检查 ===
        rate_limit_info = self._check_rate_limit(client_host, path, method)
        if rate_limit_info.get("rejected"):
            await self._send_json_error(
                send, 429, "请求过于频繁，请稍后重试", extra_headers=[
                    (b"retry-after", b"1"), (b"x-ratelimit-limit", str(rate_limit_info["limit"]).encode()), (b"x-ratelimit-remaining", b"0"), ]
            )
            return

        # === 熔断检查 ===
        service_name = self._get_service_name(path, method)
        breaker = self.breakers[service_name]
        if self.cb_enabled and not breaker.allow_request():
            await self._send_json_error(
                send, 503, f"服务 {service_name} 暂时不可用，请稍后重试", extra_headers=[
                    (b"retry-after", str(self.recovery_timeout).encode()), (b"x-circuit-state", breaker.state.value.encode()), ]
            )
            return

        # === 包装 send 以注入响应头 ===
        response_status = [200]

        async def send_wrapper(message: Message):
            if message["type"] == "http.response.start":
                response_status[0] = message.get("status", 200)
                process_time = time.time() - start_time
                # 注入自定义响应头（保留原始 headers，追加新头）
                headers = list(message.get("headers", []))
                # 检查是否已有这些头，避免重复
                existing_keys = {k.lower() for k, v in headers}
                if b"x-process-time" not in existing_keys:
                    headers.append((b"x-process-time", f"{process_time:.6f}".encode()))
                if b"x-request-id" not in existing_keys:
                    headers.append((b"x-request-id", datetime.now().strftime("%Y%m%d%H%M%S%f").encode()))
                if rate_limit_info.get("limit") and b"x-ratelimit-limit" not in existing_keys:
                    headers.append((b"x-ratelimit-limit", str(rate_limit_info["limit"]).encode()))
                    headers.append((b"x-ratelimit-remaining", str(rate_limit_info.get("remaining", 0)).encode()))
                if self.cb_enabled and b"x-circuit-state" not in existing_keys:
                    headers.append((b"x-circuit-state", breaker.state.value.encode()))
                message = {**message, "headers": headers}
            # 直接透传 body chunk —— 不缓冲！
            await send(message)

        # === 调用内层应用 ===
        try:
            await self.app(scope, receive, send_wrapper)
            # 记录成功
            if response_status[0] < 500:
                breaker.record_success()
            else:
                breaker.record_failure()
        except Exception as e:
            breaker.record_failure()
            logger.error(f"请求处理异常：{method} {path} - {e}")
            await self._send_json_error(send, 500, f"网关内部错误：{str(e)}")
            return

        # === 响应日志 ===
        process_time = time.time() - start_time
        logger.info(f"📤 响应 | {method} {path} | status: {response_status[0]} | time: {process_time:.3f}s")

    def _check_auth(self, scope: Scope, path: str) -> dict | None:
        """认证检查，返回 None 表示通过，否则返回错误信息"""
        # 跳过不需要认证的路径
        if any(path.startswith(exclude) for exclude in self.exclude_paths):
            return None

        # 从 headers 中获取 Authorization
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="replace")

        if not auth_header:
            return {"status": 401, "detail": "未提供认证信息，请在 Header 中添加 Authorization 字段"}

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return {"status": 401, "detail": "认证格式错误，应为：Bearer <token>"}

        token = parts[1]

        # 验证 token
        # 方式 1: Gateway JWT
        try:
            jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return None  # 验证成功
        except jwt.ExpiredSignatureError:
            return {"status": 401, "detail": "Token 已过期，请重新登录"}
        except jwt.InvalidTokenError:
            pass

        # 方式 2: OIDC Token（解析 payload，不验证签名）
        try:
            import base64
            parts = token.split(".")
            if len(parts) == 3:
                payload_b64 = parts[1]
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                if payload.get("sub"):
                    return None  # OIDC Token 有效
        except Exception:
            pass

        return {"status": 401, "detail": "无效的 Token"}

    def _check_rate_limit(self, client_ip: str, path: str, method: str) -> dict:
        """限流检查"""
        if not self.rate_limit_enabled:
            return {"limit": self.default_limit, "remaining": self.burst}

        route_rule = self.config.match_route(path, method)
        limit = route_rule.rate_limit if (route_rule and route_rule.rate_limit) else self.default_limit

        bucket = self.buckets[client_ip]
        if bucket.rate != limit:
            self.buckets[client_ip] = TokenBucket(limit, self.burst)
            bucket = self.buckets[client_ip]

        if not bucket.consume():
            return {"rejected": True, "limit": limit, "remaining": 0}

        return {"limit": limit, "remaining": int(bucket.tokens)}

    def _get_service_name(self, path: str, method: str) -> str:
        """获取目标服务名称"""
        route_rule = self.config.match_route(path, method)
        if route_rule:
            return route_rule.service
        for svc in self.config.services:
            if path.startswith(svc.prefix):
                return svc.name
        return "unknown"

    async def _send_json_error(
        self, send: Send, status: int, detail: str, extra_headers: list = None
    ):
        """发送 JSON 错误响应"""
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), ]
        if extra_headers:
            headers.extend(extra_headers)

        await send({
            "type": "http.response.start", "status": status, "headers": headers, })
        await send({
            "type": "http.response.body", "body": body, "more_body": False, })

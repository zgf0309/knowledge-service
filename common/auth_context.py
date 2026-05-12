# -*- coding: utf-8 -*-
"""请求身份上下文工具。

统一从 Query、Header、Authorization Token 中解析租户和用户信息。新接口优先使用
RequestContext，老接口也可以逐步迁移，避免每个服务重复写解析逻辑。
"""
import base64
import contextvars
import json
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import Request

TENANT_KEYS = ("tenant_id", "tenantId", "tenant", "corp_id", "corpId", "corpid")
USER_KEYS = ("user_id", "userId", "sub", "uid", "account_id", "accountId")
USERNAME_KEYS = ("username", "preferred_username", "name", "nickname")
_request_context_var: contextvars.ContextVar["RequestContext | None"] = contextvars.ContextVar(
    "request_context", default=None
)

@dataclass(frozen=True)
class RequestContext:
    tenant_id: str = "default"
    user_id: str = ""
    username: str = ""
    role: str = "user"
    token_payload: dict[str, Any] | None = None

def first_present(source: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def decode_jwt_payload(token: str) -> dict[str, Any]:
    """解析 JWT payload；只用于读取身份字段，不在微服务内做签名校验。"""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return {}

def get_bearer_payload(authorization: str | None) -> dict[str, Any]:
    if not authorization:
        return {}
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return {}
    return decode_jwt_payload(parts[1])

def get_header_value(headers: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = headers.get(name)
        if value and value.strip():
            return value.strip()
    return ""

def build_request_context(request: Request) -> RequestContext:
    headers = request.headers
    token_payload = get_bearer_payload(headers.get("authorization"))

    tenant_id = (
        get_header_value(
            headers,
            "x-tenant-id",
            "x-corp-id",
            "x-corpid",
            "tenant-id",
            "tenant_id",
            "tenant",
            "corp_id",
            "corpid",
        )
        or first_present(token_payload, TENANT_KEYS)
        or "default"
    )
    user_id = (
        first_present(token_payload, USER_KEYS)
        or get_header_value(headers, "x-user-id", "user-id")
    )
    username = (
        get_header_value(headers, "x-user-name", "x-username")
        or first_present(token_payload, USERNAME_KEYS)
    )
    role = (
        get_header_value(headers, "x-user-role", "x-role")
        or str(token_payload.get("role") or "user")
    )

    return RequestContext(
        tenant_id=tenant_id, user_id=user_id, username=username, role=role, token_payload=token_payload or None, )

async def get_request_context(request: Request) -> RequestContext:
    ctx = build_request_context(request)
    _request_context_var.set(ctx)
    return ctx

def get_current_request_context() -> RequestContext:
    return _request_context_var.get() or RequestContext()

def pick_tenant(ctx: RequestContext, *candidates: str | None) -> str:
    """从请求上下文获取租户；不信任前端 query/body 中的 tenant_id。"""
    return ctx.tenant_id or "default"

def pick_user(ctx: RequestContext, *candidates: str | None, default: str = "") -> str:
    """从 token/header 解析出的上下文获取用户；不信任前端传参。"""
    return ctx.user_id or default

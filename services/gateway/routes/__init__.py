# -*- coding: utf-8 -*-
"""API 路由注册。

精简版只保留前端 knowledge-web 当前需要的认证/SSO 路由。
业务接口由 gateway_routes.py 按配置转发到各微服务。
"""

from fastapi import APIRouter

from .auth import router as auth_router
from .sso import router as sso_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(sso_router)

__all__ = ["api_router"]

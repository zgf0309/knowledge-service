# -*- coding: utf-8 -*-
"""微服务应用公共工厂。

把 FastAPI 初始化、CORS、健康检查和 Nacos 注册收敛到这里，避免每个
service/main.py 都复制同一套样板代码。
"""
import os
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Iterable
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.config import settings
from common.nacos_client import (
    get_nacos_config, init_nacos, register_to_nacos, unregister_from_nacos, )

AsyncStep = Callable[[], Awaitable[None]]

def add_cors(app: FastAPI) -> None:
    """添加本地开发友好的跨域配置。"""
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

def add_health_route(app: FastAPI, service_name: str) -> None:
    """统一健康检查响应。"""

    @app.get("/health")
    async def health():
        return {
            "code": 200, "message": "success", "data": {"status": "healthy", "service": service_name}, }

async def register_nacos_if_enabled(
    *, default_service_name: str, metadata: dict | None = None, logger, ) -> bool:
    """按环境变量开关注册 Nacos；失败时记录日志但不中断本地启动。"""
    nacos_enabled = os.getenv("NACOS_ENABLED", "false").lower() == "true"
    if not nacos_enabled:
        return False

    try:
        service_name = os.getenv("SERVICE_NAME", default_service_name)
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", settings.service.port))

        init_nacos(service_name, host, port)
        await register_to_nacos(metadata=metadata or {"version": "2.0"})

        config_data = await get_nacos_config(f"{service_name}.yaml")
        if config_data:
            logger.info(f"Loaded config from Nacos: {len(config_data)} bytes")
        return True
    except Exception as exc:
        logger.error(f"Nacos initialization failed: {exc}")
        logger.warning("Continuing without Nacos...")
        return False

async def unregister_nacos_if_enabled(enabled: bool, logger) -> None:
    """按注册状态注销 Nacos。"""
    if not enabled:
        return
    try:
        await unregister_from_nacos()
    except Exception as exc:
        logger.error(f"Nacos unregistration failed: {exc}")

def create_service_lifespan(
    *, service_label: str, default_nacos_service_name: str, logger, startup_steps: Iterable[AsyncStep] = (), shutdown_steps: Iterable[AsyncStep] = (), nacos_metadata: dict | None = None, ):
    """创建通用生命周期管理器。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"Starting {service_label} service...")
        nacos_registered = await register_nacos_if_enabled(
            default_service_name=default_nacos_service_name, metadata=nacos_metadata, logger=logger, )

        for step in startup_steps:
            await step()

        logger.info(f"{service_label.capitalize()} service started on port {settings.service.port}")
        yield

        logger.info(f"Shutting down {service_label} service...")
        for step in shutdown_steps:
            await step()
        await unregister_nacos_if_enabled(nacos_registered, logger)
        logger.info(f"{service_label.capitalize()} service stopped")

    return lifespan

def create_service_app(
    *, title: str, description: str, service_name: str, lifespan, routers: Iterable[APIRouter], ) -> FastAPI:
    """创建带通用中间件和健康检查的 FastAPI 应用。"""
    app = FastAPI(
        title=title, description=description, version="1.0.0", lifespan=lifespan, )
    add_cors(app)
    for router in routers:
        app.include_router(router)
    add_health_route(app, service_name)
    return app
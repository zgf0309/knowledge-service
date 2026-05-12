# -*- coding: utf-8 -*-
"""
chat-service 入口（端口 7105）
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))  # 添加 services 目录

from fastapi import FastAPI
import uvicorn

from common.config import settings
from common.models import db_manager
from common.service_app import create_service_app, create_service_lifespan
from common.utils import get_logger

from chat_service.api import router, chat_router

logger = get_logger("chat_service_main")

async def init_database():
    await db_manager.init()
    await db_manager.create_tables()

async def close_database():
    await db_manager.close()

lifespan = create_service_lifespan(
    service_label="chat",
    default_nacos_service_name="jisure-chat",
    logger=logger,
    startup_steps=(init_database,),
    shutdown_steps=(close_database,),
    nacos_metadata={"version": "2.0", "features": "conversation,llm_inference"},
)

def create_app() -> FastAPI:
    return create_service_app(
        title="Jusure Chat Service",
        description="应用管理 + 会话 + LLM 推理微服务",
        service_name="chat-service",
        lifespan=lifespan,
        routers=(router, chat_router),
    )

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.service.host,
        port=settings.service.port,
        workers=settings.service.workers,
        reload=settings.service.debug,
    )

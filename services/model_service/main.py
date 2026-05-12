# -*- coding: utf-8 -*-
"""
model-service 入口（端口 7104）
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))  # 添加 services 目录

import uvicorn
from fastapi import FastAPI

from common.config import settings
from common.models import db_manager
from common.service_app import create_service_app, create_service_lifespan
from common.utils import get_logger

from model_service.api import router

logger = get_logger("model_service_main")

async def init_database():
    await db_manager.init()
    await db_manager.create_tables()

async def close_database():
    await db_manager.close()

lifespan = create_service_lifespan(
    service_label="model",
    default_nacos_service_name="jisure-model",
    logger=logger,
    startup_steps=(init_database,),
    shutdown_steps=(close_database,),
    nacos_metadata={"version": "2.0", "features": "model_config,prompt_management"},
)

def create_app() -> FastAPI:
    return create_service_app(
        title="Jusure Model Service",
        description="AI 模型配置管理微服务",
        service_name="model-service",
        lifespan=lifespan,
        routers=(router,),
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

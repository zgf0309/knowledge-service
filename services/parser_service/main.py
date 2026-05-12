# -*- coding: utf-8 -*-
"""
parser-service 入口（端口 7110）
"""
import sys
from pathlib import Path
from fastapi import FastAPI
import uvicorn

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# 修复导入路径 - 避免 ModuleNotFoundError
from common.config import settings
from common.models import db_manager
from common.service_app import create_service_app, create_service_lifespan
from common.utils import get_logger

# 使用绝对导入
from services.parser_service.api import router  # 使用绝对导入替代相对导入

logger = get_logger("parser_service_main")

async def init_database():
    await db_manager.init()

async def close_database():
    await db_manager.close()

lifespan = create_service_lifespan(
    service_label="parser",
    default_nacos_service_name="jisure-parser",
    logger=logger,
    startup_steps=(init_database,),
    shutdown_steps=(close_database,),
    nacos_metadata={"version": "2.0", "features": "document_parse,chunk,embedding"},
)

def create_app() -> FastAPI:
    return create_service_app(
        title="Jusure Parser Service",
        description="文档解析 + 切片管理 + Embedding 微服务",
        service_name="parser-service",
        lifespan=lifespan,
        routers=(router,),
    )

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,  # 直接传递 app 对象
        host=settings.service.host,
        port=settings.service.port,
        workers=settings.service.workers,
        reload=settings.service.debug,
    )

# -*- coding: utf-8 -*-
"""
知识库服务入口
"""
import sys
from pathlib import Path

# 动态计算项目根目录，同时兼容 Docker (/app) 与本地运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
# services 目录（这样 knowledge_service 就能被识别为模块）
sys.path.insert(0, str(_PROJECT_ROOT / "services"))

from fastapi import FastAPI
import uvicorn

from common.config import settings
from common.models import db_manager
from common.service_app import create_service_app, create_service_lifespan
from common.storage import redis_conn
from common.utils import get_logger

from services.knowledge_service.api import router  # 使用绝对导入

logger = get_logger("knowledge_service_main")

async def init_database_and_cache():
    await db_manager.init()
    await db_manager.create_tables()
    await redis_conn.connect()

async def close_database_and_cache():
    await db_manager.close()
    await redis_conn.disconnect()

lifespan = create_service_lifespan(
    service_label="knowledge",
    default_nacos_service_name="knowledge-service",
    logger=logger,
    startup_steps=(init_database_and_cache,),
    shutdown_steps=(close_database_and_cache,),
    nacos_metadata={
        "version": "2.0",
        "database": settings.mysql.database,
        "redis_host": settings.redis.host,
    },
)

def create_app() -> FastAPI:
    """创建FastAPI应用"""
    return create_service_app(
        title="Jusure Knowledge Service",
        description="知识库管理微服务",
        service_name="knowledge-service",
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

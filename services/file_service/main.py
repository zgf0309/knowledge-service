# -*- coding: utf-8 -*-
"""
file-service 入口
端口默认 7103（通过 SERVICE_PORT 环境变量配置）
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))  # 添加 services 目录

from fastapi import FastAPI
import uvicorn

from common.config import settings
from common.service_app import create_service_app, create_service_lifespan
from common.utils import get_logger

from services.file_service.api import router

logger = get_logger("file_service_main")

async def init_object_storage():
    # 确保 MinIO bucket 存在
    try:
        from common.storage import get_object_storage
        storage = get_object_storage()
        if hasattr(storage, "ensure_bucket"):
            storage.ensure_bucket()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Object storage init warning: {e}")

lifespan = create_service_lifespan(
    service_label="file",
    default_nacos_service_name="jisure-file",
    logger=logger,
    startup_steps=(init_object_storage,),
    nacos_metadata={"version": "2.0", "storage_type": "minio"},
)

def create_app() -> FastAPI:
    return create_service_app(
        title="Jusure File Service",
        description="文件存储微服务（MinIO）",
        service_name="file-service",
        lifespan=lifespan,
        routers=(router,),
    )

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "services.file_service.main:app",
        host=settings.service.host,
        port=settings.service.port,
        workers=settings.service.workers,
        reload=settings.service.debug,
    )

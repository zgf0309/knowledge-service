# -*- coding: utf-8 -*-
"""
jusure_microservices API Gateway
统一入口、认证鉴权、限流熔断、服务路由
"""
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# 添加项目路径到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
import logging
import asyncio
from datetime import datetime
from typing import Any

from common.config import get_settings
from middleware.logging import LoggingMiddleware
from middleware.auth import AuthMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.circuit_breaker import CircuitBreakerMiddleware
from middleware.prometheus import PrometheusMiddleware, metrics_handler, get_metrics_summary
from middleware.streaming_gateway import StreamingGatewayMiddleware
from middleware.health_check import health_checker, setup_health_checker
from gateway_routes import router as gateway_router
from routes import api_router
from config.gateway_config import GatewayConfig

def make_response(data: Any = None, code: int = 200, message: str = "success") -> dict:
    """创建统一响应格式 - 使用 HTTP 标准状态码"""
    return {"code": code, "message": message, "data": data}

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("API Gateway 启动中...")

    # 加载配置并设置健康检查
    config = GatewayConfig()
    setup_health_checker([s.__dict__ for s in config.services])

    # 启动后台健康检查
    asyncio.create_task(health_checker.start_background_check())
    logger.info(f"监听端口：{settings.service.port}")
    logger.info(f"调试模式：{settings.service.debug}")

    yield

    # 关闭时清理资源
    logger.info("API Gateway 关闭中...")
    health_checker.stop_background_check()
    logger.info("所有资源已释放")


app = FastAPI(
    title="jisure Microservices API Gateway",
    description="统一的 API 网关服务，提供认证、限流、路由转发等功能",
    version="1.0.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 使用纯 ASGI 中间件（不缓冲 StreamingResponse，支持 SSE 实时推送）
# 替换原有 BaseHTTPMiddleware 链，解决 SSE 流式响应被缓冲的问题
app.add_middleware(StreamingGatewayMiddleware)

# 注册路由（注意：auth_router 必须在 gateway_router 之前注册）
# /api/v1 前缀（内部服务调用）
app.include_router(api_router, prefix="/api/v1")
app.include_router(gateway_router, prefix="/api/v1")
# /api/ai 前缀（前端使用的路径）
app.include_router(api_router, prefix="/api/ai")
app.include_router(gateway_router, prefix="/api/ai")

# 健康检查
@app.get("/health")
async def health_check():
    return make_response(
        data={
            "status": "healthy",
            "service": "api-gateway",
            "version": "1.0.0"
        }
    )

# Prometheus metrics 端点
@app.get("/metrics")
async def metrics():
    """Prometheus metrics 接口"""
    return await metrics_handler(Request(scope={"type": "http"}))

# 详细健康检查
@app.get("/health/detailed")
async def health_detailed():
    """详细健康检查，包含所有微服务状态"""
    health_summary = health_checker.get_health_summary()
    metrics_summary = get_metrics_summary()

    return make_response(
        data={
            **health_summary,
            "gateway": metrics_summary,
            "timestamp": datetime.now().isoformat()
        }
    )

# 告警管理
@app.get("/alerts")
async def get_alerts():
    """获取当前活跃告警"""
    summary = health_checker.get_health_summary()
    return make_response(
        data={
            "active_alerts": summary["active_alerts"],
            "recent_alerts": summary["recent_alerts"]
        }
    )

@app.post("/alerts/{alert_index}/acknowledge")
async def acknowledge_alert(alert_index: int):
    """确认告警"""
    try:
        health_checker.acknowledge_alert(alert_index)
        return make_response(message="告警已确认")
    except IndexError:
        raise HTTPException(status_code=404, detail="告警不存在")

@app.delete("/alerts/acknowledged")
async def clear_acknowledged_alerts():
    """清除已确认的告警"""
    health_checker.clear_acknowledged_alerts()
    return make_response(message="已清除已确认的告警")

# 网关状态
@app.get("/gateway/status")
async def gateway_status():
    """获取网关运行状态"""
    config = GatewayConfig()

    # 更新服务健康状态
    for service in config.services:
        health_checker.register_service(
            name=service.name,
            endpoint=f"http://{service.host}:{service.port}{service.health_check}",
            timeout=service.timeout
        )

    return make_response(
        data={
            "status": "running",
            "version": "1.0.0",
            "routes_count": len(config.routes),
            "services": [s.__dict__ for s in config.services]
        }
    )

# 启动服务
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.service.host,
        port=settings.service.port,
        workers=settings.service.workers,
        reload=settings.service.debug,
    )

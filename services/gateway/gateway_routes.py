# -*- coding: utf-8 -*-
"""
路由转发核心逻辑
根据配置将请求转发到对应的微服务
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlencode
from config.gateway_config import GatewayConfig

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
from common.auth_context import build_request_context  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter()

# 初始化配置
config = GatewayConfig()

def _append_query_param(params: list[tuple[str, str]], key: str, value: str) -> None:
    if value and not any(existing_key == key for existing_key, _ in params):
        params.append((key, value))

def enrich_forward_headers_and_params(request: Request) -> tuple[dict, str]:
    """补齐下游服务需要的身份 Header 和 Query 参数。"""
    headers = dict(request.headers)
    for key in ["host", "content-length", "transfer-encoding"]:
        headers.pop(key, None)

    ctx = build_request_context(request)
    if ctx.tenant_id:
        headers.setdefault("x-tenant-id", ctx.tenant_id)
    if ctx.user_id:
        headers.setdefault("x-user-id", ctx.user_id)
    if ctx.username:
        headers.setdefault("x-user-name", ctx.username)
    if ctx.role:
        headers.setdefault("x-user-role", ctx.role)

    params = list(request.query_params.multi_items())
    _append_query_param(params, "tenant_id", ctx.tenant_id)
    _append_query_param(params, "user_id", ctx.user_id)
    return headers, urlencode(params, doseq=True)

async def forward_request(
    request: Request,
    service_host: str,
    service_port: int,
    target_path: str
):
    """转发请求到目标服务"""
    url = f"http://{service_host}:{service_port}{target_path}"
    
    try:
        headers, query_string = enrich_forward_headers_and_params(request)
        
        body = await request.body()
        
        # 发送请求（使用 stream=True 支持流式响应）
        client = httpx.AsyncClient(timeout=120.0)
        response = await client.send(
            client.build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=query_string
            ),
            stream=True
        )
        
        # 处理流式响应（SSE）
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            async def _stream_wrapper():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()
            
            # 过滤掉 hop-by-hop 和 uvicorn 会自动添加的头
            excluded_headers = {
                "transfer-encoding", "content-length", "connection",
                "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailers", "upgrade", "date", "server"
            }
            return StreamingResponse(
                _stream_wrapper(),
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() if k.lower() not in excluded_headers},
                media_type="text/event-stream"
            )
        
        # 普通响应
        content = await response.aread()
        await response.aclose()
        await client.aclose()
        if "application/json" in content_type:
            return JSONResponse(
                status_code=response.status_code,
                content=json.loads(content),
                headers={k: v for k, v in response.headers.items() if k.lower() not in ["transfer-encoding", "content-length"]}
            )
        else:
            return JSONResponse(
                status_code=response.status_code,
                content={"detail": content.decode("utf-8", errors="replace")},
                headers={k: v for k, v in response.headers.items() if k.lower() not in ["transfer-encoding", "content-length"]}
            )
        
    except httpx.TimeoutException as e:
        logger.error(f"请求超时：{url} - {e}")
        raise HTTPException(status_code=504, detail="请求超时，请稍后重试")
    except httpx.ConnectError as e:
        logger.error(f"连接失败：{url} - {e}")
        raise HTTPException(status_code=503, detail="服务暂时不可用")
    except Exception as e:
        logger.error(f"转发请求失败：{url} - {e}")
        raise HTTPException(status_code=500, detail=f"网关内部错误：{str(e)}")

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def gateway_handler(request: Request, path: str):
    """
    通用网关路由处理器
    
    1. 匹配路由规则
    2. 验证权限
    3. 检查限流
    4. 转发请求到目标服务
    """
    full_path = f"/{path}"
    method = request.method
    
    # 调试日志
    logger.info(f"🔍 请求: {method} {full_path}")
    
    # 匹配路由
    route_rule = config.match_route(full_path, method)
    
    # 调试日志
    if route_rule:
        logger.info(f"✅ 匹配路由: {route_rule.path} -> {route_rule.service}")
    else:
        logger.warning(f"❌ 未匹配路由，尝试按服务前缀匹配")
    
    if not route_rule:
        # 如果没有匹配的路由，尝试按服务前缀转发
        service = None
        for svc in config.services:
            if full_path.startswith(svc.prefix):
                service = svc
                break
        
        if not service:
            raise HTTPException(
                status_code=404,
                detail=f"未找到匹配的路由：{full_path}"
            )
        
        # 直接转发到该服务
        target_path = full_path
        logger.info(f"路由转发：{method} {full_path} -> {service.name}:{service.port}{target_path}")
        
        return await forward_request(
            request=request,
            service_host=service.host,
            service_port=service.port,
            target_path=target_path
        )
    
    # 使用路由规则转发
    service = config.get_service_by_name(route_rule.service)
    if not service:
        raise HTTPException(
            status_code=500,
            detail=f"路由配置错误：未找到服务 '{route_rule.service}'"
        )
    
    target_path = full_path
    if route_rule.strip_prefix:
        # 移除前缀
        prefix_to_strip = service.prefix
        if target_path.startswith(prefix_to_strip):
            target_path = target_path[len(prefix_to_strip):] or "/"
    
    logger.info(f"路由转发：{method} {full_path} -> {service.name}:{service.port}{target_path}")
    
    return await forward_request(
        request=request,
        service_host=service.host,
        service_port=service.port,
        target_path=target_path
    )

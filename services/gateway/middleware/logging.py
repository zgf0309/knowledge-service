# -*- coding: utf-8 -*-
"""
请求日志中间件
记录每个请求的详细信息，用于审计和性能分析
"""
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import time
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request, call_next):
        # 记录请求开始时间
        start_time = time.time()
        
        # 提取请求信息
        client_host = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        
        # 记录请求
        logger.info(
            f"📥 请求 | {client_host} | {method} {path} | "
            f"params: {json.dumps(query_params, ensure_ascii=False)}"
        )
        
        # 处理请求
        try:
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 记录响应
            logger.info(
                f"📤 响应 | {method} {path} | "
                f"status: {response.status_code} | "
                f"time: {process_time:.3f}s"
            )
            
            # 添加响应头（请求处理时间）
            response.headers["X-Process-Time"] = str(process_time)
            response.headers["X-Request-ID"] = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            
            return response
            
        except Exception as e:
            # 记录异常
            process_time = time.time() - start_time
            logger.error(
                f"❌ 异常 | {method} {path} | "
                f"time: {process_time:.3f}s | "
                f"error: {str(e)}",
                exc_info=True
            )
            raise

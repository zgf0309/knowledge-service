# -*- coding: utf-8 -*-
"""
限流中间件
使用令牌桶算法限制请求频率，防止 API 滥用
"""
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import HTTPException
import time
from collections import defaultdict
from config.gateway_config import GatewayConfig
import logging

logger = logging.getLogger(__name__)

class TokenBucket:
    """令牌桶实现"""
    
    def __init__(self, rate: int, burst: int):
        """
        初始化令牌桶
        
        Args:
            rate: 令牌生成速率（个/秒）
            burst: 桶容量（最大令牌数）
        """
        self.rate = rate  # 每秒生成的令牌数
        self.burst = burst  # 桶的最大容量
        self.tokens = burst  # 当前令牌数
        self.last_update = time.time()  # 上次更新时间
    
    def consume(self, tokens: int = 1) -> bool:
        """
        消费令牌
        
        Args:
            tokens: 需要消费的令牌数
        
        Returns:
            bool: 是否成功消费
        """
        now = time.time()
        elapsed = now - self.last_update
        
        # 添加新令牌（按时间流逝计算）
        new_tokens = elapsed * self.rate
        self.tokens = min(self.burst, self.tokens + new_tokens)
        self.last_update = now
        
        # 检查是否有足够的令牌
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.config = GatewayConfig()
        rate_cfg = self.config.rate_limit_config
        
        self.enabled = rate_cfg.get("enabled", True)
        self.default_limit = rate_cfg.get("default_limit", 100)
        self.burst = rate_cfg.get("burst", 200)
        
        # 按 IP 地址维护令牌桶
        self.buckets = defaultdict(lambda: TokenBucket(self.default_limit, self.burst))
        
        logger.info(f"限流中间件已启用：{self.default_limit} req/s, burst={self.burst}")
    
    async def dispatch(self, request, call_next):
        # 如果限流未启用，直接放行
        if not self.enabled:
            return await call_next(request)
        
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"
        
        # 检查路由特定的限流配置
        path = request.url.path
        route_rule = self.config.match_route(path, request.method)
        
        if route_rule and route_rule.rate_limit:
            limit = route_rule.rate_limit
        else:
            limit = self.default_limit
        
        # 获取或创建令牌桶
        bucket = self.buckets[client_ip]
        
        # 更新限流配置（如果变化）
        if bucket.rate != limit:
            self.buckets[client_ip] = TokenBucket(limit, self.burst)
            bucket = self.buckets[client_ip]
        
        # 尝试消费令牌
        if not bucket.consume():
            logger.warning(f"限流触发：{client_ip} - {request.method} {path}")
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请稍后重试",
                headers={
                    "Retry-After": "1",  # 建议 1 秒后重试
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0"
                }
            )
        
        # 添加限流响应头
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))
        
        return response

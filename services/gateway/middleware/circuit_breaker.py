# -*- coding: utf-8 -*-
"""
熔断器中间件
当服务连续失败时，快速失败，避免雪崩效应
"""
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import HTTPException
import time
from enum import Enum
from collections import defaultdict
from config.gateway_config import GatewayConfig
import logging

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态，允许请求通过
    OPEN = "open"         # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，尝试恢复

class CircuitBreaker:
    """熔断器实现"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30):
        """
        初始化熔断器
        
        Args:
            failure_threshold: 失败阈值（达到后打开熔断器）
            recovery_timeout: 恢复超时时间（秒）
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
    
    def record_success(self):
        """记录成功"""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            logger.warning(f"熔断器打开：failure_count={self.failure_count}")
            self.state = CircuitState.OPEN
    
    def allow_request(self) -> bool:
        """
        检查是否允许请求通过
        
        Returns:
            bool: 是否允许请求
        """
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # 检查是否应该尝试恢复
            if self.last_failure_time and \
               (time.time() - self.last_failure_time) >= self.recovery_timeout:
                logger.info("熔断器进入半开状态")
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        
        # HALF_OPEN 状态，允许一个请求尝试
        return True

class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """熔断器中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.config = GatewayConfig()
        cb_cfg = self.config.circuit_breaker_config
        
        self.enabled = cb_cfg.get("enabled", True)
        self.failure_threshold = cb_cfg.get("failure_threshold", 5)
        self.recovery_timeout = cb_cfg.get("recovery_timeout", 30)
        self.timeout_seconds = cb_cfg.get("timeout_seconds", 30)
        
        # 按服务维护熔断器
        self.breakers = defaultdict(
            lambda: CircuitBreaker(self.failure_threshold, self.recovery_timeout)
        )
        
        logger.info(
            f"熔断器中间件已启用："
            f"threshold={self.failure_threshold}, "
            f"recovery={self.recovery_timeout}s"
        )
    
    async def dispatch(self, request, call_next):
        # 如果熔断器未启用，直接放行
        if not self.enabled:
            return await call_next(request)
        
        # 获取目标服务名称（从路由或路径推断）
        path = request.url.path
        route_rule = self.config.match_route(path, request.method)
        
        if route_rule:
            service_name = route_rule.service
        else:
            # 尝试从路径推断服务
            service_name = "unknown"
            for svc in self.config.services:
                if path.startswith(svc.prefix):
                    service_name = svc.name
                    break
        
        # 获取该服务的熔断器
        breaker = self.breakers[service_name]
        
        # 检查是否允许请求
        if not breaker.allow_request():
            logger.warning(f"熔断器打开，拒绝请求：{service_name} - {path}")
            raise HTTPException(
                status_code=503,
                detail=f"服务 {service_name} 暂时不可用，请稍后重试",
                headers={
                    "Retry-After": str(self.recovery_timeout),
                    "X-Circuit-State": breaker.state.value
                }
            )
        
        try:
            # 执行请求（带超时控制）
            import asyncio
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds
            )
            
            # 检查响应状态码
            if response.status_code < 500:
                breaker.record_success()
            else:
                breaker.record_failure()
            
            # 添加熔断器状态响应头
            response.headers["X-Circuit-State"] = breaker.state.value
            
            return response
            
        except asyncio.TimeoutError:
            logger.error(f"请求超时：{service_name} - {path}")
            breaker.record_failure()
            raise HTTPException(
                status_code=504,
                detail=f"服务 {service_name} 响应超时",
                headers={"X-Circuit-State": breaker.state.value}
            )
        except Exception as e:
            logger.error(f"请求失败：{service_name} - {path} - {e}")
            breaker.record_failure()
            raise

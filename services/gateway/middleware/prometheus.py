# -*- coding: utf-8 -*-
"""
Prometheus Metrics 中间件
提供请求监控、性能指标、健康检查等功能
"""
import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import os

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
except ImportError:
    Counter = Histogram = Gauge = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest():
        return b"# prometheus_client is not installed\n"

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

class _NoopMetric:
    def labels(self, **kwargs):
        return self

    def inc(self):
        pass

    def dec(self):
        pass

    def observe(self, value):
        pass

    def set(self, value):
        pass

def _counter(*args, **kwargs):
    return Counter(*args, **kwargs) if Counter else _NoopMetric()

def _histogram(*args, **kwargs):
    return Histogram(*args, **kwargs) if Histogram else _NoopMetric()

def _gauge(*args, **kwargs):
    return Gauge(*args, **kwargs) if Gauge else _NoopMetric()

# ==================== Prometheus Metrics 定义 ====================

# HTTP 请求计数器
http_requests_total = _counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

# HTTP 请求延迟直方图
http_request_duration_seconds = _histogram(
    'http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# HTTP 请求大小直方图
http_request_size_bytes = _histogram(
    'http_request_size_bytes',
    'HTTP request size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000)
)

# HTTP 响应大小直方图
http_response_size_bytes = _histogram(
    'http_response_size_bytes',
    'HTTP response size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000)
)

# 活跃请求数
active_requests = _gauge(
    'active_requests',
    'Number of active requests'
)

# 系统 CPU 使用率
system_cpu_usage_percent = _gauge(
    'system_cpu_usage_percent',
    'System CPU usage percentage'
)

# 系统内存使用率
system_memory_usage_percent = _gauge(
    'system_memory_usage_percent',
    'System memory usage percentage'
)

# 进程 CPU 使用率
process_cpu_usage_percent = _gauge(
    'process_cpu_usage_percent',
    'Process CPU usage percentage'
)

# 进程内存使用率
process_memory_usage_percent = _gauge(
    'process_memory_usage_percent',
    'Process memory usage percentage'
)

# 服务健康状态
service_health_status = _gauge(
    'service_health_status',
    'Service health status (1=healthy, 0=unhealthy)',
    ['service']
)

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Prometheus 监控中间件"""
    
    def __init__(self, app, app_name: str = "api-gateway"):
        super().__init__(app)
        self.app_name = app_name
        self.process = psutil.Process(os.getpid()) if psutil else None
        
    async def dispatch(self, request: Request, call_next) -> Response:
        # 记录开始时间
        start_time = time.time()
        
        # 增加活跃请求数
        active_requests.inc()
        
        # 获取请求信息
        method = request.method
        endpoint = self._get_endpoint(request)
        
        try:
            # 处理请求
            response = await call_next(request)
            
            # 记录请求指标
            duration = time.time() - start_time
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=response.status_code
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)
            
            # 记录请求大小
            content_length = request.headers.get('content-length')
            if content_length:
                http_request_size_bytes.labels(
                    method=method,
                    endpoint=endpoint
                ).observe(float(content_length))
            
            # 记录响应大小
            content_length = response.headers.get('content-length')
            if content_length:
                http_response_size_bytes.labels(
                    method=method,
                    endpoint=endpoint
                ).observe(float(content_length))
            
            return response
            
        except Exception as e:
            # 记录异常
            logger.error(f"请求处理异常：{e}")
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=500
            ).inc()
            raise
        finally:
            # 减少活跃请求数
            active_requests.dec()
            
            # 更新系统和进程指标
            self._update_system_metrics()
    
    def _get_endpoint(self, request: Request) -> str:
        """提取端点路径（去除动态参数）"""
        path = request.url.path
        
        # 简化路径，例如 /api/v1/knowledge/123 -> /api/v1/knowledge/{id}
        # 这里可以根据实际路由规则进一步优化
        parts = path.split('/')
        simplified_parts = []
        for part in parts:
            if part.isdigit():
                simplified_parts.append('{id}')
            else:
                simplified_parts.append(part)
        
        return '/'.join(simplified_parts)
    
    def _update_system_metrics(self):
        """更新系统和进程指标"""
        try:
            if psutil is None or self.process is None:
                return
            # 系统 CPU 和内存
            system_cpu_usage_percent.set(psutil.cpu_percent(interval=1))
            system_memory_usage_percent.set(psutil.virtual_memory().percent)
            
            # 进程 CPU 和内存
            process_cpu_usage_percent.set(self.process.cpu_percent(interval=1))
            process_memory_info = self.process.memory_info()
            total_memory = psutil.virtual_memory().total
            process_memory_usage_percent.set((process_memory_info.rss / total_memory) * 100)
            
        except Exception as e:
            logger.error(f"更新系统指标失败：{e}")

def update_health_status(service_name: str, is_healthy: bool):
    """更新服务健康状态"""
    status = 1.0 if is_healthy else 0.0
    service_health_status.labels(service=service_name).set(status)

async def metrics_handler(request: Request):
    """Prometheus metrics 接口"""
    from fastapi.responses import Response
    
    # 更新所有服务的健康状态
    update_health_status("api-gateway", True)
    
    # 生成 metrics
    metrics = generate_latest()
    
    return Response(
        content=metrics,
        media_type=CONTENT_TYPE_LATEST
    )

def get_metrics_summary() -> dict:
    """获取指标摘要（用于 API 返回）"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "metrics": {
            "http_requests_total": "Counter metric for total HTTP requests",
            "http_request_duration_seconds": "Histogram metric for request latency",
            "http_request_size_bytes": "Histogram metric for request size",
            "http_response_size_bytes": "Histogram metric for response size",
            "active_requests": "Gauge metric for active requests",
            "system_cpu_usage_percent": "Gauge metric for system CPU usage",
            "system_memory_usage_percent": "Gauge metric for system memory usage",
            "process_cpu_usage_percent": "Gauge metric for process CPU usage",
            "process_memory_usage_percent": "Gauge metric for process memory usage",
            "service_health_status": "Gauge metric for service health status"
        },
        "prometheus_endpoint": "/metrics",
        "health_endpoint": "/health/detailed"
    }

# -*- coding: utf-8 -*-
"""
健康检查与告警模块
提供详细的服务健康检查和告警功能
"""
import asyncio
import logging
import time
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger("health_check")


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceHealth:
    """单个服务的健康信息"""

    def __init__(self, name: str, endpoint: str, timeout: int = 5):
        self.name = name
        self.endpoint = endpoint
        self.timeout = timeout
        self.status = HealthStatus.UNHEALTHY
        self.last_check: float | None = None
        self.last_error: str | None = None
        self.response_time: float | None = None
        self.consecutive_failures = 0
        self.total_checks = 0
        self.successful_checks = 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name, "endpoint": self.endpoint, "status": self.status.value, "last_check": datetime.fromtimestamp(self.last_check).isoformat() if self.last_check else None, "last_error": self.last_error, "response_time_ms": round(self.response_time * 1000, 2) if self.response_time else None, "consecutive_failures": self.consecutive_failures, "success_rate": round((self.successful_checks / self.total_checks * 100), 2) if self.total_checks > 0 else 0
        }

class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class Alert:
    """告警信息"""
    
    def __init__(self, level: AlertLevel, service: str, message: str):
        self.level = level
        self.service = service
        self.message = message
        self.timestamp = datetime.now()
        self.acknowledged = False
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "level": self.level.value, "service": self.service, "message": self.message, "timestamp": self.timestamp.isoformat(), "acknowledged": self.acknowledged
        }

class HealthChecker:
    """健康检查器"""
    
    def __init__(self):
        self.services: dict[str, ServiceHealth] = {}
        self.alerts: list[Alert] = []
        self.max_alerts = 100
        self.check_interval = 30  # 默认 30 秒检查一次
        self.failure_threshold = 3  # 连续失败 3 次触发告警
        self._running = False
        self._task: asyncio.Task | None = None
    
    def register_service(self, name: str, endpoint: str, timeout: int = 5):
        """注册服务健康检查"""
        self.services[name] = ServiceHealth(name, endpoint, timeout)
        logger.info(f"注册健康检查服务：{name} -> {endpoint}")
    
    async def check_service(self, service: ServiceHealth) -> bool:
        """检查单个服务"""
        start_time = time.time()
        service.total_checks += 1
        
        try:
            async with httpx.AsyncClient(timeout=service.timeout) as client:
                response = await client.get(service.endpoint)
                
                service.response_time = time.time() - start_time
                service.last_check = time.time()
                
                if response.status_code == 200:
                    service.status = HealthStatus.HEALTHY
                    service.consecutive_failures = 0
                    service.successful_checks += 1
                    service.last_error = None
                    return True
                else:
                    service.status = HealthStatus.DEGRADED
                    service.consecutive_failures += 1
                    service.last_error = f"HTTP {response.status_code}"
                    return False
                    
        except asyncio.TimeoutError:
            service.status = HealthStatus.UNHEALTHY
            service.consecutive_failures += 1
            service.last_error = "Request timeout"
            service.last_check = time.time()
            return False
            
        except Exception as e:
            service.status = HealthStatus.UNHEALTHY
            service.consecutive_failures += 1
            service.last_error = str(e)
            service.last_check = time.time()
            return False
    
    def create_alert(self, service_name: str, message: str, level: AlertLevel = AlertLevel.WARNING):
        """创建告警"""
        alert = Alert(level, service_name, message)
        self.alerts.append(alert)
        
        # 限制告警数量
        if len(self.alerts) > self.max_alerts:
            self.alerts.pop(0)
        
        logger.warning(f"[{level.value.upper()}] {service_name}: {message}")
    
    async def check_all_services(self):
        """检查所有服务"""
        tasks = []
        for service in self.services.values():
            tasks.append(self.check_service(service))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查是否需要创建告警
        self._check_alerts()
    
    def _check_alerts(self):
        """检查并创建告警"""
        for service in self.services.values():
            if service.consecutive_failures >= self.failure_threshold:
                # 连续失败达到阈值，创建严重告警
                if not any(a.service == service.name and not a.acknowledged 
                          for a in self.alerts if a.level == AlertLevel.CRITICAL):
                    self.create_alert(
                        service.name, f"服务连续失败 {service.consecutive_failures} 次，最后错误：{service.last_error}", AlertLevel.CRITICAL
                    )
            elif service.consecutive_failures > 0:
                # 有失败但未达阈值，创建警告
                recent_warning = next(
                    (a for a in self.alerts 
                     if a.service == service.name 
                     and a.level == AlertLevel.WARNING 
                     and not a.acknowledged), None
                )
                
                if not recent_warning:
                    self.create_alert(
                        service.name, f"服务检查失败 {service.consecutive_failures} 次，最后错误：{service.last_error}", AlertLevel.WARNING
                    )
    
    def acknowledge_alert(self, alert_index: int):
        """确认告警"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True
            logger.info(f"已确认告警：{self.alerts[alert_index].message}")
    
    def clear_acknowledged_alerts(self):
        """清除已确认的告警"""
        self.alerts = [a for a in self.alerts if not a.acknowledged]
    
    async def start_background_check(self):
        """启动后台定期检查"""
        self._running = True
        
        async def check_loop():
            while self._running:
                try:
                    await self.check_all_services()
                except Exception as e:
                    logger.error(f"健康检查循环异常：{e}")
                
                await asyncio.sleep(self.check_interval)
        
        self._task = asyncio.create_task(check_loop())
        logger.info(f"启动后台健康检查，间隔：{self.check_interval}秒")
    
    def stop_background_check(self):
        """停止后台检查"""
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("停止后台健康检查")
    
    def get_health_summary(self) -> dict:
        """获取健康摘要"""
        total_services = len(self.services)
        healthy_count = sum(1 for s in self.services.values() if s.status == HealthStatus.HEALTHY)
        degraded_count = sum(1 for s in self.services.values() if s.status == HealthStatus.DEGRADED)
        unhealthy_count = sum(1 for s in self.services.values() if s.status == HealthStatus.UNHEALTHY)
        
        # 确定整体状态
        if unhealthy_count > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY
        
        return {
            "status": overall_status.value, "total_services": total_services, "healthy": healthy_count, "degraded": degraded_count, "unhealthy": unhealthy_count, "active_alerts": sum(1 for a in self.alerts if not a.acknowledged), "services": {name: service.to_dict() for name, service in self.services.items()}, "recent_alerts": [a.to_dict() for a in self.alerts[-10:] if not a.acknowledged], "last_check": max(
                (s.last_check for s in self.services.values() if s.last_check), default=None
            )
        }

# 全局健康检查器实例
health_checker = HealthChecker()

def setup_health_checker(services_config: list[dict]):
    """设置健康检查器"""
    for service in services_config:
        health_checker.register_service(
            name=service["name"], endpoint=f"http://{service['host']}:{service['port']}{service.get('health_check', '/health')}", timeout=service.get("timeout", 5)
        )
    
    # 注意：不在这里启动后台检查，由 FastAPI 生命周期事件管理
    # asyncio.create_task(health_checker.start_background_check())

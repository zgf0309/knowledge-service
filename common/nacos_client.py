# -*- coding: utf-8 -*-
"""
Nacos 服务注册与配置管理客户端

提供统一的服务注册、配置拉取、配置监听等功能
"""

import os
import json
import time
from typing import Any, Callable
import logging

try:
    import nacos
except ImportError:
    nacos = None

logger = logging.getLogger("nacos")


class NacosClientManager:
    """Nacos 客户端管理器（单例）"""
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.nacos_client = None
            self.service_name = ""
            self.host = ""
            self.port = 0
            self.registered = False
            self.config_cache: dict[str, str] = {}
    
    @classmethod
    def reset(cls):
        """重置单例（用于测试）"""
        cls._instance = None
        cls._initialized = False
    
    def initialize(self, service_name: str, host: str = "0.0.0.0", port: int = 0) -> bool:
        """
        初始化 Nacos 客户端
        
        Args:
            service_name: 服务名称（如：knowledge-service）
            host: 服务绑定地址
            port: 服务端口
            
        Returns:
            bool: 是否成功初始化
        """
        if nacos is None:
            logger.warning("nacos-sdk-python not installed, skipping Nacos initialization")
            return False
        
        try:
            # 从环境变量读取配置
            nacos_server = os.getenv("NACOS_SERVER", "localhost:8848")
            nacos_namespace = os.getenv("NACOS_NAMESPACE", "jisure")
            nacos_group = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
            
            self.service_name = service_name
            self.host = host
            self.port = port
            
            # 创建 Nacos 客户端
            self.nacos_client = nacos.NacosClient(
                server_urls=[nacos_server], namespace=nacos_namespace, username=os.getenv("NACOS_USERNAME", ""), password=os.getenv("NACOS_PASSWORD", "")
            )
            
            logger.info(f"Nacos client initialized: server={nacos_server}, namespace={nacos_namespace}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Nacos client: {e}")
            return False
    
    async def register_service(self, metadata: dict[str, str] | None = None) -> bool:
        """
        注册服务到 Nacos
        
        Args:
            metadata: 服务元数据（版本、环境等）
            
        Returns:
            bool: 是否注册成功
        """
        if not self.nacos_client or self.registered:
            return False
        
        try:
            default_metadata = {
                "version": "2.0", "environment": os.getenv("ENVIRONMENT", "development"), "start_time": str(int(time.time())), "language": "python"
            }
            
            if metadata:
                default_metadata.update(metadata)
            
            self.nacos_client.add_naming_instance(
                service_name=self.service_name, ip=self.host, port=self.port, cluster_name="DEFAULT", weight=1.0, enable=True, healthy=True, metadata=default_metadata
            )
            
            self.registered = True
            logger.info(f"✅ Service {self.service_name} registered to Nacos at {self.host}:{self.port}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to register service to Nacos: {e}")
            return False
    
    async def unregister_service(self) -> bool:
        """
        从 Nacos 注销服务
        
        Returns:
            bool: 是否注销成功
        """
        if not self.nacos_client or not self.registered:
            return False
        
        try:
            self.nacos_client.remove_naming_instance(
                service_name=self.service_name, ip=self.host, port=self.port, cluster_name="DEFAULT"
            )
            
            self.registered = False
            logger.info(f"✅ Service {self.service_name} unregistered from Nacos")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to unregister service from Nacos: {e}")
            return False
    
    async def get_config(self, data_id: str, group: str = "DEFAULT_GROUP", timeout: int = 5000) -> str | None:
        """
        从 Nacos 获取配置
        
        Args:
            data_id: 配置 Data ID
            group: 配置分组
            timeout: 超时时间（毫秒）
            
        Returns:
            str: 配置内容，失败返回 None
        """
        if not self.nacos_client:
            return None
        
        try:
            config = self.nacos_client.get_config(data_id=data_id, group=group, timeout=timeout)
            
            # 缓存配置
            cache_key = f"{data_id}:{group}"
            self.config_cache[cache_key] = config
            
            logger.info(f"📄 Config loaded from Nacos: {data_id} ({len(config)} bytes)")
            return config
            
        except Exception as e:
            logger.error(f"❌ Failed to get config from Nacos: {e}")
            
            # 返回缓存的配置（降级方案）
            cache_key = f"{data_id}:{group}"
            if cache_key in self.config_cache:
                logger.warning(f"Using cached config for {data_id}")
                return self.config_cache[cache_key]
            
            return None
    
    def add_config_listener(self, data_id: str, group: str, callback: Callable[[str, str, str], None]) -> bool:
        """
        添加配置变更监听器
        
        Args:
            data_id: 配置 Data ID
            group: 配置分组
            callback: 回调函数 (data_id, group, content)
            
        Returns:
            bool: 是否添加成功
        """
        if not self.nacos_client:
            return False
        
        try:
            self.nacos_client.add_config_change_listener(
                data_id=data_id, group=group, callback=lambda d, g, c: callback(d, g, c)
            )
            
            logger.info(f"🔔 Config listener added: {data_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to add config listener: {e}")
            return False
    
    async def get_service_instances(self, service_name: str, clusters: str = "DEFAULT") -> list[dict[str, Any]]:
        """
        获取服务实例列表（服务发现）
        
        Args:
            service_name: 服务名称
            clusters: 集群名称
            
        Returns:
            list[Dict]: 服务实例列表
        """
        if not self.nacos_client:
            return []
        
        try:
            instances = self.nacos_client.get_naming_instance(
                service_name=service_name, clusters=clusters
            )
            
            logger.info(f"Found {len(instances)} instance(s) for service {service_name}")
            return instances
            
        except Exception as e:
            logger.error(f"❌ Failed to get service instances: {e}")
            return []
    
    def is_registered(self) -> bool:
        """检查服务是否已注册"""
        return self.registered
    
    def get_client(self):
        """获取原始 Nacos 客户端"""
        return self.nacos_client

# 全局单例
nacos_manager = NacosClientManager()

def init_nacos(service_name: str, host: str = "0.0.0.0", port: int = 0) -> bool:
    """
    便捷函数：初始化 Nacos 客户端
    
    Args:
        service_name: 服务名称
        host: 服务地址
        port: 服务端口
        
    Returns:
        bool: 是否成功初始化
    """
    return nacos_manager.initialize(service_name, host, port)

async def register_to_nacos(metadata: dict[str, str] | None = None) -> bool:
    """
    便捷函数：注册服务到 Nacos
    
    Args:
        metadata: 服务元数据
        
    Returns:
        bool: 是否注册成功
    """
    return await nacos_manager.register_service(metadata)

async def unregister_from_nacos() -> bool:
    """
    便捷函数：从 Nacos 注销服务
    
    Returns:
        bool: 是否注销成功
    """
    return await nacos_manager.unregister_service()

async def get_nacos_config(data_id: str, group: str = "DEFAULT_GROUP") -> str | None:
    """
    便捷函数：从 Nacos 获取配置
    
    Args:
        data_id: 配置 Data ID
        group: 配置分组
        
    Returns:
        str: 配置内容
    """
    return await nacos_manager.get_config(data_id, group)

def add_nacos_config_listener(data_id: str, group: str, callback: Callable) -> bool:
    """
    便捷函数：添加配置变更监听器
    
    Args:
        data_id: 配置 Data ID
        group: 配置分组
        callback: 回调函数
        
    Returns:
        bool: 是否添加成功
    """
    return nacos_manager.add_config_listener(data_id, group, callback)

async def get_service_instances(service_name: str) -> list[dict[str, Any]]:
    """
    便捷函数：获取服务实例列表
    
    Args:
        service_name: 服务名称
        
    Returns:
        list[Dict]: 服务实例列表
    """
    return await nacos_manager.get_service_instances(service_name)

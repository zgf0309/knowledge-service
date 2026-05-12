# -*- coding: utf-8 -*-
"""
Redis连接和消息队列 - 参考 ragflow 的 RedisConn 设计
支持任务队列、分布式锁、缓存
"""
import os
import json
import asyncio
import uuid
from typing import Any, Callable
from functools import wraps
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis

from common.config import settings
from common.utils import get_logger

logger = get_logger("redis")

class RedisConnection:
    """Redis连接管理"""
    
    def __init__(self):
        self.config = settings.redis
        self._pool: redis.ConnectionPool | None = None
        self._client: Redis | None = None
    
    async def connect(self):
        """建立连接"""
        if self._client is None:
            self._pool = redis.ConnectionPool.from_url(
                self.config.connection_url, decode_responses=True
            )
            self._client = Redis(connection_pool=self._pool)
            logger.info(f"Redis connected: {self.config.host}:{self.config.port}")
    
    async def disconnect(self):
        """断开连接"""
        if self._client:
            await self._client.close()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
            logger.info("Redis disconnected")
    
    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

redis_conn = RedisConnection()

class RedisMessageQueue:
    """Redis消息队列 - 基于Stream实现"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
    
    async def produce(self, queue_name: str, message: dict[str, Any]) -> str:
        """生产消息到队列"""
        payload = {"message": json.dumps(message, ensure_ascii=False)}
        msg_id = await self.redis.xadd(queue_name, payload)
        logger.debug(f"Produced message to {queue_name}: {msg_id}")
        return msg_id
    
    async def consume(
        self, queue_name: str, group_name: str, consumer_name: str, count: int = 1, block: int = 5000
    ) -> list[dict[str, Any]]:
        """从队列消费消息"""
        try:
            await self.redis.xgroup_create(
                queue_name, group_name, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        
        messages = await self.redis.xreadgroup(
            groupname=group_name, consumername=consumer_name, streams={queue_name: ">"}, count=count, block=block
        )
        
        result = []
        if messages:
            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    try:
                        message = json.loads(msg_data.get("message", "{}"))
                        message["_msg_id"] = msg_id
                        result.append(message)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode message: {msg_id}")
        
        return result
    
    async def ack(self, queue_name: str, group_name: str, msg_id: str):
        """确认消息"""
        await self.redis.xack(queue_name, group_name, msg_id)
        logger.debug(f"Acked message: {msg_id}")
    
    async def pending_messages(
        self, queue_name: str, group_name: str, min_idle_time: int = 60000
    ) -> list[Dict]:
        """获取待处理消息（用于重试超时任务）"""
        pending = await self.redis.xpending_range(
            queue_name, group_name, min="-", max="+", count=100
        )
        
        result = []
        for item in pending:
            if item.get("time_since_delivered", 0) > min_idle_time:
                result.append(item)
        
        return result

class DistributedLock:
    """分布式锁"""
    
    def __init__(self, redis_client: Redis, lock_name: str, timeout: int = 30, retry_interval: float = 0.1):
        self.redis = redis_client
        self.lock_name = f"lock:{lock_name}"
        self.timeout = timeout
        self.retry_interval = retry_interval
        self.identifier = str(uuid.uuid4())
    
    async def acquire(self, max_retries: int = 100) -> bool:
        """获取锁"""
        for _ in range(max_retries):
            acquired = await self.redis.set(
                self.lock_name, self.identifier, nx=True, ex=self.timeout
            )
            if acquired:
                logger.debug(f"Acquired lock: {self.lock_name}")
                return True
            await asyncio.sleep(self.retry_interval)
        return False
    
    async def release(self):
        """释放锁"""
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await self.redis.eval(script, 1, self.lock_name, self.identifier)
        logger.debug(f"Released lock: {self.lock_name}")
    
    @asynccontextmanager
    async def __call__(self, max_retries: int = 100):
        """上下文管理器方式使用"""
        acquired = await self.acquire(max_retries)
        if not acquired:
            raise TimeoutError(f"Failed to acquire lock: {self.lock_name}")
        try:
            yield
        finally:
            await self.release()

class CacheManager:
    """缓存管理器"""
    
    def __init__(self, redis_client: Redis, prefix: str = "cache:"):
        self.redis = redis_client
        self.prefix = prefix
    
    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"
    
    async def get(self, key: str) -> Any | None:
        """获取缓存"""
        value = await self.redis.get(self._key(key))
        if value:
            return json.loads(value)
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 3600):
        """设置缓存"""
        await self.redis.set(
            self._key(key), json.dumps(value, ensure_ascii=False), ex=ttl
        )
    
    async def delete(self, key: str):
        """删除缓存"""
        await self.redis.delete(self._key(key))
    
    async def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        return await self.redis.exists(self._key(key)) > 0

def get_message_queue() -> RedisMessageQueue:
    """获取消息队列实例"""
    return RedisMessageQueue(redis_conn.client)

def get_cache_manager() -> CacheManager:
    """获取缓存管理器"""
    return CacheManager(redis_conn.client)
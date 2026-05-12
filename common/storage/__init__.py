# -*- coding: utf-8 -*-

class StorageException(Exception):
    """存储操作异常"""
    pass

from .object_store import ObjectStorage, MinIOStorage, get_object_storage, StorageFactory
from .redis_store import (
    redis_conn, RedisConnection, 
    RedisMessageQueue, DistributedLock, CacheManager,
    get_message_queue, get_cache_manager
)
from .vector_store import (
    VectorStore, ElasticsearchVectorStore, SearchResult,
    VectorStoreFactory, get_vector_store
)

__all__ = [
    "ObjectStorage", "MinIOStorage", "get_object_storage", "StorageFactory",
    "redis_conn", "RedisConnection", "RedisMessageQueue", 
    "DistributedLock", "CacheManager", "get_message_queue", "get_cache_manager",
    "VectorStore", "ElasticsearchVectorStore", "SearchResult",
    "VectorStoreFactory", "get_vector_store"
]
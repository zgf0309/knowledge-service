# -*- coding: utf-8 -*-
"""
存储抽象层 - 参考 ragflow 的 DocStoreConnection 设计
支持多种存储后端：MinIO, S3, Azure, OSS, GCS
"""
import os
import json
from abc import ABC, abstractmethod
from io import BytesIO
from functools import wraps
from typing import Any, Dict

from minio import Minio
from minio.error import S3Error

from common.config import settings
from common.utils.exceptions import StorageException
from common.utils.logger import get_logger

logger = get_logger("storage")

def singleton(cls):
    """单例装饰器"""
    instances = {}
    
    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    return get_instance

class ObjectStorage(ABC):
    """对象存储抽象基类"""
    
    @abstractmethod
    async def put(self, bucket: str, object_name: str, data: bytes, metadata: Dict | None = None) -> bool:
        """上传对象"""
        pass
    
    @abstractmethod
    async def get(self, bucket: str, object_name: str) -> bytes:
        """获取对象"""
        pass
    
    @abstractmethod
    async def delete(self, bucket: str, object_name: str) -> bool:
        """删除对象"""
        pass
    
    @abstractmethod
    async def exists(self, bucket: str, object_name: str) -> bool:
        """检查对象是否存在"""
        pass
    
    @abstractmethod
    async def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        """列出对象"""
        pass
    
    @abstractmethod
    async def get_url(self, bucket: str, object_name: str, expires: int = 3600) -> str:
        """获取预签名URL"""
        pass

@singleton
class MinIOStorage(ObjectStorage):
    """MinIO存储实现"""
    
    def __init__(self):
        self.config = settings.minio
        self.client = Minio(
            self.config.endpoint, access_key=self.config.access_key, secret_key=self.config.secret_key, secure=self.config.secure
        )
        self.default_bucket = self.config.bucket
    
    def _get_bucket(self, bucket: str | None = None) -> str:
        return bucket or self.default_bucket
    
    async def put(self, bucket: str, object_name: str, data: bytes, metadata: Dict | None = None) -> bool:
        bucket = self._get_bucket(bucket)
        try:
            self.client.put_object(
                bucket, object_name, BytesIO(data), length=len(data), metadata=metadata or {}
            )
            logger.info(f"Put object: {bucket}/{object_name}, size: {len(data)}")
            return True
        except S3Error as e:
            logger.error(f"Failed to put object: {e}")
            raise StorageException(f"Failed to put object: {e}", "minio")
    
    async def get(self, bucket: str, object_name: str) -> bytes:
        bucket = self._get_bucket(bucket)
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to get object: {e}")
            raise StorageException(f"Failed to get object: {e}", "minio")
    
    async def delete(self, bucket: str, object_name: str) -> bool:
        bucket = self._get_bucket(bucket)
        try:
            self.client.remove_object(bucket, object_name)
            logger.info(f"Deleted object: {bucket}/{object_name}")
            return True
        except S3Error as e:
            logger.error(f"Failed to delete object: {e}")
            raise StorageException(f"Failed to delete object: {e}", "minio")
    
    async def exists(self, bucket: str, object_name: str) -> bool:
        bucket = self._get_bucket(bucket)
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False
    
    async def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        bucket = self._get_bucket(bucket)
        try:
            objects = self.client.list_objects(bucket, prefix=prefix)
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"Failed to list objects: {e}")
            raise StorageException(f"Failed to list objects: {e}", "minio")
    
    async def get_url(self, bucket: str, object_name: str, expires: int = 3600) -> str:
        bucket = self._get_bucket(bucket)
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                bucket, object_name, expires=timedelta(seconds=expires)
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to get presigned URL: {e}")
            raise StorageException(f"Failed to get presigned URL: {e}", "minio")
    
    def ensure_bucket(self, bucket: str | None = None):
        """确保bucket存在"""
        bucket = self._get_bucket(bucket)
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)
            logger.info(f"Created bucket: {bucket}")

class StorageFactory:
    """存储工厂"""
    
    _instances: dict[str, ObjectStorage] = {}
    
    @classmethod
    def get_storage(cls, storage_type: str = "minio") -> ObjectStorage:
        """获取存储实例"""
        if storage_type not in cls._instances:
            if storage_type == "minio":
                cls._instances[storage_type] = MinIOStorage()
            elif storage_type == "s3":
                cls._instances[storage_type] = MinIOStorage()
            else:
                raise StorageException(f"Unsupported storage type: {storage_type}")
        return cls._instances[storage_type]

def get_object_storage() -> ObjectStorage:
    """获取对象存储实例"""
    storage_type = os.getenv("OBJECT_STORAGE_TYPE", "minio")
    return StorageFactory.get_storage(storage_type)

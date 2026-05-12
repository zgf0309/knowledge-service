# -*- coding: utf-8 -*-
"""
自定义异常类
"""
from typing import Any

class JusureException(Exception):
    """基础异常类"""
    
    def __init__(self, message: str, code: str | None = None, details: Any | None = None):
        self.message = message
        self.code = code or "UNKNOWN_ERROR"
        self.details = details
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        result = {
            "code": self.code, "message": self.message
        }
        if self.details:
            result["details"] = self.details
        return result

class ValidationException(JusureException):
    """参数验证异常"""
    
    def __init__(self, message: str, field: str | None = None):
        self.field = field
        super().__init__(message, code="VALIDATION_ERROR", details={"field": field} if field else None)

class NotFoundException(JusureException):
    """资源不存在异常"""
    
    def __init__(self, resource: str, resource_id: str | None = None):
        self.resource = resource
        self.resource_id = resource_id
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with id '{resource_id}' not found"
        super().__init__(message, code="NOT_FOUND")

class UnauthorizedException(JusureException):
    """未授权异常"""
    
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, code="UNAUTHORIZED")

class ForbiddenException(JusureException):
    """禁止访问异常"""
    
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, code="FORBIDDEN")

class StorageException(JusureException):
    """存储异常"""
    
    def __init__(self, message: str, storage_type: str | None = None):
        self.storage_type = storage_type
        super().__init__(message, code="STORAGE_ERROR", details={"storage_type": storage_type})

class TaskException(JusureException):
    """任务执行异常"""
    
    def __init__(self, message: str, task_id: str | None = None, retry_count: int = 0):
        self.task_id = task_id
        self.retry_count = retry_count
        super().__init__(
            message, code="TASK_ERROR", details={"task_id": task_id, "retry_count": retry_count}
        )

class LLMException(JusureException):
    """LLM调用异常"""
    
    def __init__(self, message: str, model: str | None = None):
        self.model = model
        super().__init__(message, code="LLM_ERROR", details={"model": model})

class EmbeddingException(JusureException):
    """向量嵌入异常"""
    
    def __init__(self, message: str, text_length: int | None = None):
        self.text_length = text_length
        super().__init__(message, code="EMBEDDING_ERROR", details={"text_length": text_length})
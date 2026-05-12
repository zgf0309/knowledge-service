# -*- coding: utf-8 -*-
"""
统一响应格式工具
与 jusure_AI 对齐的响应格式
"""
from typing import Any
import time
import uuid

def make_response(
    data: Any = None, code: int = 200, message: str = "success", req_id: str | None = None
) -> Dict:
    """
    创建标准响应格式 - 使用 HTTP 标准状态码

    Args:
        data: 响应数据
        code: HTTP 状态码 (200=成功，400=请求错误，500=服务器错误)
        message: 消息
        req_id: 请求 ID（用于追踪）

    Returns:
        标准响应字典
    """
    if req_id is None:
        req_id = uuid.uuid4().hex

    return {
        "code": code, "timestamp": int(time.time()), "message": message, "data": data if data is not None else {}, "req_id": req_id
    }

def success_response(data: Any = None, message: str = "success", req_id: str | None = None) -> Dict:
    """成功响应 - HTTP 200"""
    return make_response(data=data, message=message, req_id=req_id)

def error_response(message: str = "error", req_id: str | None = None) -> Dict:
    """错误响应 - 默认 HTTP 500"""
    return make_response(data=None, message=message, req_id=req_id)

def api_success(data: Any = None, message: str = "成功", req_id: str | None = None) -> Dict:
    """业务接口成功响应。"""
    return make_response(data=data, code=200, message=message, req_id=req_id)

def api_error(
    message: str = "失败", code: int = 500, req_id: str | None = None, ) -> Dict:
    """业务接口错误响应。"""
    return make_response(data={}, code=code, message=message, req_id=req_id)
# -*- coding: utf-8 -*-
"""
通用工具函数
"""
import uuid
import hashlib
import time
from datetime import datetime
from typing import Any

def generate_id(prefix: str = "") -> str:
    """生成唯一ID"""
    unique_id = uuid.uuid4().hex[:16]
    if prefix:
        return f"{prefix}_{unique_id}"
    return unique_id

def generate_snowflake_id() -> int:
    """生成雪花ID (简化版本)"""
    timestamp = int(time.time() * 1000)
    random_part = uuid.uuid4().int & 0xFFFFFF
    return (timestamp << 24) | random_part

def md5_hash(content: str) -> str:
    """计算MD5哈希"""
    return hashlib.md5(content.encode()).hexdigest()

def sha256_hash(content: str) -> str:
    """计算SHA256哈希"""
    return hashlib.sha256(content.encode()).hexdigest()

def now_timestamp() -> int:
    """获取当前时间戳 (毫秒)"""
    return int(time.time() * 1000)

def now_datetime() -> datetime:
    """获取当前时间"""
    return datetime.utcnow()

def format_datetime(dt: datetime | None = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化时间"""
    if dt is None:
        dt = datetime.utcnow()
    return dt.strftime(fmt)

def parse_datetime(dt_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """解析时间字符串"""
    return datetime.strptime(dt_str, fmt)

def chunk_list(lst: list, chunk_size: int) -> list:
    """列表分块"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def safe_get(d: Dict, *keys, default: Any = None) -> Any:
    """安全获取嵌套字典值"""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, default)
        else:
            return default
    return d

def calculate_content_hash(content: str, metadata: Dict | None = None) -> str:
    """计算内容哈希，用于去重"""
    hash_content = content
    if metadata:
        hash_content += str(sorted(metadata.items()))
    return sha256_hash(hash_content)

def truncate_text(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def clean_text(text: str) -> str:
    """清理文本 (移除多余空白)"""
    import re
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
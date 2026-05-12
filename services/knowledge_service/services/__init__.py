# -*- coding: utf-8 -*-
"""
Knowledge Service 子服务模块
"""
# 从父目录的 core_services.py 导入核心服务类（使用绝对导入）
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_services import (
    KnowledgeBaseService,
    DocumentService,
    TaskService,
    KnowledgeExtService,
)

__all__ = [
    "KnowledgeBaseService",
    "DocumentService",
    "TaskService",
    "KnowledgeExtService",
]

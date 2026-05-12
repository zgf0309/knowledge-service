# -*- coding: utf-8 -*-
"""
Database utilities - 兼容层
提供数据库相关的基础工具函数
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# 从 models.database 导入真实的实现
from common.models.database import db_manager, DatabaseManager

# 这里放置一些通用的数据库操作函数
# 目前作为占位模块，后续可以根据需要添加具体功能

def get_db_connection():
    """获取数据库连接（示例）"""
    # TODO: 实现真实的数据库连接逻辑
    pass

async def execute_query(query, params=None):
    """执行 SQL 查询（示例）"""
    # TODO: 实现真实的查询执行逻辑
    pass

# 数据库会话管理
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（委托给 DatabaseManager）"""
    from common.models.database import db_manager
    async with db_manager.get_session() as session:
        yield session

__all__ = ["db_manager", "DatabaseManager", "get_db_session", "get_db_connection", "execute_query"]
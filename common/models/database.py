# -*- coding: utf-8 -*-
"""
数据库连接管理
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import sessionmaker

from common.config import settings
from common.utils import get_logger
from .models import Base

logger = get_logger("database")

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        self.engine = None
        self.async_session_factory = None
    
    async def init(self):
        """初始化数据库连接"""
        self.engine = create_async_engine(
            settings.mysql.connection_url, pool_size=settings.mysql.pool_size, max_overflow=settings.mysql.max_connections - settings.mysql.pool_size, pool_pre_ping=True, echo=settings.service.debug
        )
        
        self.async_session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        logger.info(f"Database connected: {settings.mysql.host}:{settings.mysql.port}")
    
    async def create_tables(self):
        """创建所有表（如果不存在）"""
        from sqlalchemy import inspect
        
        async with self.engine.begin() as conn:
            # 使用同步方式检查已存在的表
            # inspect 可以直接在 sync_connection 上使用
            def _check_and_create_tables(connection):
                inspector = inspect(connection)
                existing_tables = set(inspector.get_table_names())

                # 只创建不存在的表，并忽略已存在索引的错误
                for table_name, table in Base.metadata.tables.items():
                    if table_name not in existing_tables:
                        try:
                            table.create(connection)
                            logger.info(f"Created table: {table_name}")
                        except Exception as e:
                            logger.warning(f"Table creation warning for {table_name}: {e}")

                if not existing_tables:
                    logger.info("Created all database tables")
                else:
                    logger.info(f"Tables already exist: {len(existing_tables)} tables")

            await conn.run_sync(_check_and_create_tables)
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取数据库会话"""
        async with self.async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

db_manager = DatabaseManager()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入获取数据库会话"""
    async with db_manager.get_session() as session:
        yield session
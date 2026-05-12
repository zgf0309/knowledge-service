# -*- coding: utf-8 -*-
"""
MySQL 向量检索实现
直接从 MySQL 查询 chunks 和向量，进行余弦相似度计算
"""
import json
import math
from typing import Any
from dataclasses import dataclass
from common.database import db_manager
from common.utils.logger import get_logger

logger = get_logger("mysql_vector")


@dataclass
class ChunkResult:
    id: str = ""
    score: float = 0.0
    content: str = ""
    metadata: dict[str, Any] | None = None
    vector: list[float] | None = None

def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    if len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)

class MySQLVectorSearch:
    """
    MySQL 向量检索器
    直接从 MySQL 查询 chunks 表，使用余弦相似度进行检索
    """
    
    def __init__(self):
        pass
    
    async def search(
        self, tenant_id: str, kb_ids: list[str], query_vector: list[float], top_k: int = 10, min_score: float = 0.0, filters: dict[str, Any] | None = None, ) -> list[ChunkResult]:
        """
        向量相似度检索
        
        Args:
            tenant_id: 租户 ID
            kb_ids: 知识库 ID 列表
            query_vector: 查询向量
            top_k: 返回数量
            min_score: 最小相似度分数
            filters: 过滤条件
        """
        try:
            from sqlalchemy import select, text
            
            # 构建查询
            kb_ids_str = "', '".join(kb_ids)
            
            # 直接查询 chunks 表
            sql = text(f"""
                SELECT 
                    id, doc_id, kb_id, content, vector, token_num, chunk_metadata, create_time, update_time
                FROM chunk 
                WHERE tenant_id = :tenant_id 
                AND kb_id IN ('{kb_ids_str}')
                AND status = '1'
                AND vector IS NOT NULL
                AND LENGTH(vector) > 10
            """)
            
            async with db_manager.get_session() as session:
                result = await session.execute(sql, {"tenant_id": tenant_id})
                rows = result.fetchall()
                
                if not rows:
                    logger.warning(f"No chunks found for tenant={tenant_id}, kb_ids={kb_ids}")
                    return []
                
                # 计算相似度
                results = []
                for row in rows:
                    chunk_id = row[0]
                    doc_id = row[1]
                    kb_id = row[2]
                    content = row[3]
                    vector_str = row[4]
                    token_num = row[5]
                    chunk_metadata = row[6]
                    
                    # 解析向量
                    try:
                        chunk_vector = json.loads(vector_str) if vector_str else []
                    except:
                        continue
                    
                    # 计算余弦相似度
                    score = cosine_similarity(query_vector, chunk_vector)
                    
                    # 应用过滤条件
                    if filters:
                        if "doc_id" in filters and doc_id != filters["doc_id"]:
                            continue
                        if "kb_id" in filters and kb_id != filters["kb_id"]:
                            continue
                    
                    # 应用最小分数过滤
                    if score >= min_score:
                        results.append(ChunkResult(
                            id=chunk_id, score=score, content=content or "", metadata={
                                "doc_id": doc_id, "kb_id": kb_id, "token_num": token_num, "chunk_metadata": chunk_metadata or {}
                            }, vector=chunk_vector
                        ))
                
                # 按分数降序排序
                results.sort(key=lambda x: x.score, reverse=True)
                
                return results[:top_k]
                
        except Exception as e:
            logger.error(f"MySQL vector search failed: {e}")
            return []
    
    async def text_search(
        self, tenant_id: str, kb_ids: list[str], query_text: str, top_k: int = 10, filters: dict[str, Any] | None = None, ) -> list[ChunkResult]:
        """
        全文检索（基于 MySQL LIKE）
        
        Args:
            tenant_id: 租户 ID
            kb_ids: 知识库 ID 列表
            query_text: 查询文本
            top_k: 返回数量
            filters: 过滤条件
        """
        try:
            from sqlalchemy import select, text
            
            kb_ids_str = "', '".join(kb_ids)
            
            # 使用 LIKE 进行全文匹配
            sql = text(f"""
                SELECT 
                    id, doc_id, kb_id, content, vector, token_num, chunk_metadata
                FROM chunk 
                WHERE tenant_id = :tenant_id 
                AND kb_id IN ('{kb_ids_str}')
                AND status = '1'
                AND content LIKE :query_text
                ORDER BY LENGTH(content) ASC
            """)
            
            async with db_manager.get_session() as session:
                result = await session.execute(sql, {
                    "tenant_id": tenant_id, "query_text": f"%{query_text}%"
                })
                rows = result.fetchall()
                
                if not rows:
                    logger.warning(f"No text matches found for tenant={tenant_id}, kb_ids={kb_ids}")
                    return []
                
                results = []
                for row in rows[:top_k]:
                    results.append(ChunkResult(
                        id=row[0], score=1.0, # 文本匹配给满分
                        content=row[3] or "", metadata={
                            "doc_id": row[1], "kb_id": row[2], "token_num": row[5], "chunk_metadata": row[6] or {}
                        }
                    ))
                
                return results
                
        except Exception as e:
            logger.error(f"MySQL text search failed: {e}")
            return []
    
    async def get_chunks_by_doc_id(
        self, tenant_id: str, doc_id: str, page: int = 1, page_size: int = 100, ) -> tuple[list[ChunkResult], int]:
        """
        根据文档ID获取所有切片
        
        Args:
            tenant_id: 租户 ID
            doc_id: 文档 ID
            page: 页码（从1开始）
            page_size: 每页数量
        
        Returns:
            (chunks, total): 切片列表和总数
        """
        try:
            from sqlalchemy import select, func, text
            
            # 每次调用时直接创建新session，避免缓存问题
            if db_manager.async_session_factory is None:
                logger.error("Database not initialized")
                return [], 0
            
            offset = (page - 1) * page_size
            
            async with db_manager.get_session() as session:
                # 查询总数
                count_sql = text("""
                    SELECT COUNT(*) FROM chunk 
                    WHERE tenant_id = :tenant_id 
                    AND doc_id = :doc_id 
                    AND status = '1'
                """)
                count_result = await session.execute(count_sql, {
                    "tenant_id": tenant_id, "doc_id": doc_id
                })
                count_row = count_result.fetchone()
                total = count_row[0] if count_row else 0

                if total == 0:
                    logger.info(f"No chunks found for doc_id={doc_id}")
                    return [], 0
                
                # 查询切片列表
                sql = text("""
                    SELECT 
                        id, doc_id, kb_id, content, vector, token_num, page_num, position, chunk_metadata, create_time, update_time
                    FROM chunk 
                    WHERE tenant_id = :tenant_id 
                    AND doc_id = :doc_id 
                    AND status = '1'
                    ORDER BY position ASC
                    LIMIT :limit OFFSET :offset
                """)
                
                result = await session.execute(sql, {
                    "tenant_id": tenant_id, "doc_id": doc_id, "limit": page_size, "offset": offset
                })
                rows = result.fetchall()
                
                results = []
                for row in rows:
                    results.append(ChunkResult(
                        id=row[0], score=1.0, content=row[3] or "", metadata={
                            "doc_id": row[1], "kb_id": row[2], "token_num": row[5], "page_num": row[6], "position": row[7], "chunk_metadata": row[8] or {}, "create_time": row[9], "update_time": row[10]
                        }
                    ))
                
                return results, total
                
        except Exception as e:
            logger.error(f"Get chunks by doc_id failed: {e}")
            return [], 0

    async def hybrid_search(
        self, tenant_id: str, kb_ids: list[str], query_vector: list[float], query_text: str, top_k: int = 10, min_score: float = 0.0, vector_weight: float = 0.7, filters: dict[str, Any] | None = None, ) -> list[ChunkResult]:
        """
        混合检索：向量 + 文本，使用 RRF 融合
        
        Args:
            tenant_id: 租户 ID
            kb_ids: 知识库 ID 列表
            query_vector: 查询向量
            query_text: 查询文本
            top_k: 返回数量
            min_score: 最小分数
            vector_weight: 向量权重
            filters: 过滤条件
        """
        try:
            # 并行执行向量检索和文本检索
            vector_results = await self.search(
                tenant_id=tenant_id, kb_ids=kb_ids, query_vector=query_vector, top_k=top_k * 2, min_score=min_score, filters=filters, )
            
            text_results = await self.text_search(
                tenant_id=tenant_id, kb_ids=kb_ids, query_text=query_text, top_k=top_k * 2, filters=filters, )
            
            # RRF (Reciprocal Rank Fusion) 融合
            rrf_results: dict[str, dict] = {}
            
            # 添加向量检索结果
            for rank, result in enumerate(vector_results):
                rrf_score = 1.0 / (60 + rank + 1)  # RRF 公式
                result_id = f"v_{result.id}"
                rrf_results[result.id] = {
                    "id": result.id, "score": rrf_score * vector_weight, "content": result.content, "metadata": result.metadata, "vector": result.vector, }
            
            # 添加文本检索结果
            text_weight = 1 - vector_weight
            for rank, result in enumerate(text_results):
                rrf_score = 1.0 / (60 + rank + 1)  # RRF 公式
                if result.id in rrf_results:
                    rrf_results[result.id]["score"] += rrf_score * text_weight
                else:
                    rrf_results[result.id] = {
                        "id": result.id, "score": rrf_score * text_weight, "content": result.content, "metadata": result.metadata, "vector": result.vector, }
            
            # 排序并返回
            merged = sorted(rrf_results.values(), key=lambda x: x["score"], reverse=True)
            
            return [
                ChunkResult(
                    id=r["id"], score=r["score"], content=r["content"], metadata=r["metadata"], vector=r.get("vector")
                )
                for r in merged[:top_k]
            ]
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []

# 全局单例
_mysql_vector_search: MySQLVectorSearch | None = None

def get_mysql_vector_search() -> MySQLVectorSearch:
    """获取 MySQL 向量检索器单例"""
    global _mysql_vector_search
    if _mysql_vector_search is None:
        _mysql_vector_search = MySQLVectorSearch()
    return _mysql_vector_search
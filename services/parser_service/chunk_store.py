# -*- coding: utf-8 -*-
"""
parser-service chunk_store
切片向量库 CRUD 封装，直接使用 Elasticsearch 底层 client
参考 ragflow api/apps/chunk_app.py list_chunk / set / rm / create 逻辑
"""
from typing import Any

from common.config import settings
from common.storage import get_vector_store
from common.utils import get_logger, EmbeddingModel, aembed_chunks, astore_chunks

logger = get_logger("chunk_store")

def _index_name(tenant_id: str, kb_id: str) -> str:
    """向量索引名称规则: jusure_{tenant_id}_{kb_id}"""
    return f"jusure_{tenant_id}_{kb_id}"

class ChunkStore:
    """
    切片存储操作 —— 直接操作 ES
    ragflow 参考：api/apps/chunk_app.py 中的 retrieval_test / list_chunk / set / rm
    """

    def __init__(self):
        self._vector_store = get_vector_store()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list_chunks(
        self, tenant_id: str, kb_id: str, doc_id: str | None = None, keyword: str | None = None, chunk_id: str | None = None, page: int = 1, page_size: int = 20, status: str | None = None, chunk_type: str | None = None, with_stats: bool = False, ) -> dict[str, Any]:
        """
        分页查询切片列表
        返回 {total, chunks: [...], stats: {original_count, custom_count}}  (with_stats=True 时)
        参考 ragflow chunk_app.list_chunk
        """
        index = _index_name(tenant_id, kb_id)
        must = []
        if doc_id:
            must.append({"term": {"doc_id": doc_id}})
        if status:
            must.append({"term": {"status": status}})
        if chunk_id:
            must.append({"term": {"_id": chunk_id}})
        if chunk_type:
            must.append({"term": {"chunk_type": chunk_type}})

        query: dict[str, Any] = {"bool": {"must": must}} if must else {"match_all": {}}
        if keyword:
            query = {
                "bool": {
                    "must": must, "should": [{"match": {"content": keyword}}], "minimum_should_match": 1, }
            }

        try:
            # 检查索引是否存在
            if not await self._vector_store.index_exists(index):
                return {"total": 0, "chunks": []}

            result = await self._vector_store.search(
                index_name=index, query_text=keyword, top_k=page_size, from_=(page - 1) * page_size, filters={key: value for key, value in {
                    "doc_id": doc_id, "status": status, "chunk_type": chunk_type, "id": chunk_id, }.items() if value}, )
            
            hits = []
            for hit in result.get("hits", []):
                hits.append(hit)
            
            response = {
                "total": result.get("total", 0), "chunks": hits, }
            
            # 如果需要统计信息，分别查询原文和自定义切片数量
            if with_stats and doc_id:
                stats = await self._get_chunk_type_stats(tenant_id, kb_id, doc_id)
                response["stats"] = stats
            
            return response
        except Exception as e:
            logger.warning(f"list_chunks error (index may not exist): {e}")
            return {"total": 0, "chunks": []}

    async def _get_chunk_type_stats(
        self, tenant_id: str, kb_id: str, doc_id: str, ) -> dict[str, int]:
        """分别统计原文切片和自定义切片数量"""
        index = _index_name(tenant_id, kb_id)
        original_count = 0
        custom_count = 0
        
        try:
            original_results = await self._vector_store.search(
                index_name=index, top_k=1, filters={"doc_id": doc_id, "chunk_type": "original"}, )
            original_count = original_results.get("total", 0)
            
            custom_results = await self._vector_store.search(
                index_name=index, top_k=1, filters={"doc_id": doc_id, "chunk_type": "custom"}, )
            custom_count = custom_results.get("total", 0)
        except Exception as e:
            logger.warning(f"_get_chunk_type_stats error: {e}")
        
        return {"original_count": original_count, "custom_count": custom_count}

    async def get_chunk(self, tenant_id: str, kb_id: str, chunk_id: str) -> Dict | None:
        """获取单条切片"""
        index = _index_name(tenant_id, kb_id)
        try:
            if not await self._vector_store.index_exists(index):
                return None
            result = await self._vector_store.get_by_ids(index, [chunk_id])
            return result[0] if result else None
        except Exception as e:
            logger.warning(f"get_chunk error: {e}")
            return None

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def upsert_chunk(
        self, tenant_id: str, kb_id: str, chunk_id: str, doc: dict[str, Any], ) -> bool:
        """新增或更新切片（不重跑 embedding）"""
        index = _index_name(tenant_id, kb_id)
        try:
            # 确保索引存在
            if not await self._vector_store.index_exists(index):
                dimension = len(doc.get("vector") or []) or settings.vector_store.embedding_dims
                await self._vector_store.create_index(index, dimension)
                logger.info(f"Created ES index: {index}")

            await self._vector_store.insert(index, [{**doc, "id": chunk_id, "chunk_id": chunk_id}])
            return True
        except Exception as e:
            logger.error(f"upsert_chunk error: {e}")
            return False

    async def delete_chunk(self, tenant_id: str, kb_id: str, chunk_id: str) -> bool:
        """删除单条切片"""
        index = _index_name(tenant_id, kb_id)
        try:
            await self._vector_store.delete(index, [chunk_id])
            return True
        except Exception as e:
            logger.error(f"delete_chunk error: {e}")
            return False

    async def delete_by_doc(self, tenant_id: str, kb_id: str, doc_id: str) -> int:
        """删除文档下所有切片，返回删除数量"""
        index = _index_name(tenant_id, kb_id)
        try:
            if not await self._vector_store.index_exists(index):
                return 0
            result = await self._vector_store.search(index, top_k=5000, filters={"doc_id": doc_id})
            doc_ids = [item.get("id") for item in result.get("hits", []) if item.get("id")]
            if not doc_ids:
                return 0
            return await self._vector_store.delete(index, doc_ids)
        except Exception as e:
            logger.error(f"delete_by_doc error: {e}")
            return 0

    # ------------------------------------------------------------------
    # 向量检索（用于切片检索测试，完整 RAG 检索在 rag-service）
    # ------------------------------------------------------------------

    async def similarity_search(
        self, tenant_id: str, kb_id: str, query_vector: list[float], top_k: int = 5, doc_id: str | None = None, ) -> list[Dict]:
        """KNN 向量相似检索"""
        index = _index_name(tenant_id, kb_id)
        try:
            if not await self._vector_store.index_exists(index):
                return []
            result = await self._vector_store.search(
                index_name=index, query_vector=query_vector, top_k=top_k, filters={"doc_id": doc_id} if doc_id else None, )
            return result.get("hits", [])
        except Exception as e:
            logger.warning(f"similarity_search error: {e}")
            return []
# -*- coding: utf-8 -*-
"""
向量存储抽象层 - 参考 ragflow 的 DocStoreConnection 设计
支持 Elasticsearch, Qdrant, Milvus 等多种向量数据库
"""
import os
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

import httpx

from common.config import settings
from common.utils.exceptions import StorageException
from common.utils.logger import get_logger

logger = get_logger("vector_store")

@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    content: str
    metadata: dict[str, Any]
    vector: list[float] | None = None

class VectorStore(ABC):
    """向量存储抽象基类"""
    
    @abstractmethod
    async def create_index(self, index_name: str, dimension: int, metadata_schema: Dict | None = None) -> bool:
        """创建索引"""
        pass
    
    @abstractmethod
    async def delete_index(self, index_name: str) -> bool:
        """删除索引"""
        pass
    
    @abstractmethod
    async def index_exists(self, index_name: str) -> bool:
        """检查索引是否存在"""
        pass
    
    @abstractmethod
    async def insert(self, index_name: str, documents: list[dict[str, Any]]) -> int:
        """插入文档 (包含向量和元数据)"""
        pass
    
    @abstractmethod
    async def update(self, index_name: str, doc_id: str, document: dict[str, Any]) -> bool:
        """更新文档"""
        pass
    
    @abstractmethod
    async def delete(self, index_name: str, doc_ids: list[str]) -> int:
        """删除文档"""
        pass
    
    @abstractmethod
    async def search(
        self, index_name: str, query_vector: list[float] | None = None, query_text: str | None = None, top_k: int = 10, filters: Dict | None = None, min_score: float = 0.0, from_: int = 0, ) -> dict[str, Any]:
        """搜索 (向量搜索或全文搜索)"""
        pass
    
    @abstractmethod
    async def hybrid_search(
        self, index_name: str, query_vector: list[float], query_text: str, top_k: int = 10, filters: Dict | None = None, vector_weight: float = 0.7
    ) -> list[SearchResult]:
        """混合搜索 (向量 + 全文)"""
        pass
    
    @abstractmethod
    async def get_by_ids(self, index_name: str, doc_ids: list[str]) -> list[Dict]:
        """根据ID获取文档"""
        pass

class ElasticsearchVectorStore(VectorStore):
    """Elasticsearch向量存储实现"""
    
    def __init__(self):
        self.config = settings.elasticsearch
        self.base_url = self.config.connection_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)
        self.dimension = settings.vector_store.embedding_dims
        self._mapping_cache: dict[str, dict[str, Any]] = {}
        self._vector_dim_cache: dict[str, int] = {}

    async def _get_properties(self, index_name: str) -> dict[str, Any]:
        if index_name not in self._mapping_cache:
            response = await self._request("GET", f"/{index_name}/_mapping")
            data = response.json()
            index_mapping = data.get(index_name) or next(iter(data.values()), {})
            self._mapping_cache[index_name] = (
                index_mapping.get("mappings", {}).get("properties", {}) or {}
            )
        return self._mapping_cache[index_name]

    async def _get_vector_dims(self, index_name: str) -> int | None:
        if index_name not in self._vector_dim_cache:
            properties = await self._get_properties(index_name)
            dims = properties.get("vector", {}).get("dims")
            if isinstance(dims, int):
                self._vector_dim_cache[index_name] = dims
        return self._vector_dim_cache.get(index_name)

    async def _filter_field(self, index_name: str, key: str) -> str:
        if key == "_id" or key.endswith(".keyword"):
            return key
        properties = await self._get_properties(index_name)
        field_mapping = properties.get(key) or {}
        if field_mapping.get("type") == "text" and "keyword" in field_mapping.get("fields", {}):
            return f"{key}.keyword"
        return key

    @staticmethod
    def _vector_norm(vector: list[float]) -> float:
        total = 0.0
        for value in vector:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(number):
                return 0.0
            total += number * number
        return math.sqrt(total)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response
    
    async def create_index(self, index_name: str, dimension: int, metadata_schema: Dict | None = None) -> bool:
        mapping = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"}, "content": {
                        "type": "text"
                    }, "vector": {
                        "type": "dense_vector", "dims": dimension, "index": True, "similarity": "cosine"
                    }, "metadata": {"type": "object", "enabled": True}, "tenant_id": {"type": "keyword"}, "kb_id": {"type": "keyword"}, "knowledge_id": {"type": "keyword"}, "doc_id": {"type": "keyword"}, "chunk_id": {"type": "keyword"}, "status": {"type": "keyword"}, "chunk_type": {"type": "keyword"}, "created_at": {"type": "date"}, "updated_at": {"type": "date"}
                }
            }, "settings": {
                "number_of_shards": 1, "number_of_replicas": 0
            }
        }
        
        if metadata_schema:
            for field, field_type in metadata_schema.items():
                mapping["mappings"]["properties"][field] = field_type
        
        try:
            await self._request("PUT", f"/{index_name}", json=mapping)
            logger.info(f"Created ES index: {index_name}")
            return True
        except httpx.HTTPStatusError as e:
            if "resource_already_exists_exception" in str(e):
                return True
            body = e.response.text
            if e.response.status_code == 400 and "resource_already_exists_exception" in body:
                return True
            logger.error(f"Failed to create index: {body}")
            raise StorageException(f"Failed to create index: {body}", "elasticsearch")
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            raise StorageException(f"Failed to create index: {e}", "elasticsearch")
    
    async def delete_index(self, index_name: str) -> bool:
        try:
            await self._request("DELETE", f"/{index_name}")
            logger.info(f"Deleted ES index: {index_name}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return True
            logger.error(f"Failed to delete index: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete index: {e}")
            return False
    
    async def index_exists(self, index_name: str) -> bool:
        try:
            await self._request("GET", f"/{index_name}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
    
    async def insert(self, index_name: str, documents: list[dict[str, Any]]) -> int:
        lines = []
        for doc in documents:
            source = {
                "id": doc.get("id"), "content": doc.get("content", ""), "vector": doc.get("vector"), "metadata": doc.get("metadata", {}), "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at")
            }
            for key in ["tenant_id", "kb_id", "knowledge_id", "doc_id", "chunk_id", "source"]:
                if key in doc:
                    source[key] = doc[key]
            lines.append(json.dumps({"index": {"_index": index_name, "_id": doc.get("id")}}, ensure_ascii=False))
            lines.append(json.dumps(source, ensure_ascii=False))
        
        try:
            response = await self._request(
                "POST", "/_bulk", content="\n".join(lines) + "\n", headers={"Content-Type": "application/x-ndjson"}, )
            result = response.json()
            if result.get("errors"):
                failed = [item for item in result.get("items", []) if item.get("index", {}).get("error")]
                raise StorageException(f"Bulk insert had {len(failed)} failed items", "elasticsearch")
            await self._request("POST", f"/{index_name}/_refresh")
            success = len(result.get("items", []))
            logger.info(f"Inserted {success} documents to {index_name}")
            return success
        except Exception as e:
            logger.error(f"Failed to insert documents: {e}")
            raise StorageException(f"Failed to insert documents: {e}", "elasticsearch")
    
    async def update(self, index_name: str, doc_id: str, document: dict[str, Any]) -> bool:
        try:
            await self._request("POST", f"/{index_name}/_update/{doc_id}", json={"doc": document})
            return True
        except Exception as e:
            logger.error(f"Failed to update document: {e}")
            return False
    
    async def delete(self, index_name: str, doc_ids: list[str]) -> int:
        try:
            body = {
                "query": {
                    "terms": {"_id": doc_ids}
                }
            }
            result = (await self._request("POST", f"/{index_name}/_delete_by_query", json=body)).json()
            deleted = result.get("deleted", 0)
            logger.info(f"Deleted {deleted} documents from {index_name}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            return 0
    
    async def search(
        self, index_name: str, query_vector: list[float] | None = None, query_text: str | None = None, top_k: int = 10, filters: Dict | None = None, min_score: float = 0.0, from_: int = 0, ) -> dict[str, Any]:
        """
        搜索 (向量搜索或全文搜索)
        返回 {total, hits: [{id, score, content, metadata, ...}]}
        """
        query: dict[str, Any] = {"bool": {"must": []}}
        body: dict[str, Any] = {"size": top_k, "from": from_}

        if query_vector:
            expected_dims = await self._get_vector_dims(index_name)
            actual_dims = len(query_vector)
            if expected_dims and actual_dims != expected_dims:
                logger.warning(
                    f"Skip ES vector search: index={index_name}, "
                    f"query_dim={actual_dims}, index_dim={expected_dims}"
                )
                return {"total": 0, "hits": []}

            vector_norm = self._vector_norm(query_vector)
            if vector_norm <= 0:
                logger.warning(
                    f"Skip ES vector search: index={index_name}, "
                    f"query vector is empty/zero/invalid, dim={actual_dims}"
                )
                return {"total": 0, "hits": []}

            body.pop("from", None)
            body["knn"] = {
                "field": "vector", "query_vector": query_vector, "k": top_k, "num_candidates": max(top_k * 4, 20), }
        
        if query_text:
            query["bool"]["must"].append({
                "match": {
                    "content": query_text
                }
            })
        if filters:
            filter_clauses = []
            for key, value in filters.items():
                field = await self._filter_field(index_name, key)
                filter_clauses.append({"term": {field: value}})
            if query_vector and not query_text:
                body["knn"]["filter"] = filter_clauses
            else:
                query["bool"].setdefault("filter", []).extend(filter_clauses)
        try:
            if query["bool"]["must"] or query["bool"].get("filter"):
                body["query"] = query
            if min_score:
                body["min_score"] = min_score
            result = (await self._request("POST", f"/{index_name}/_search", json=body)).json()
            
            hits = []
            for hit in result["hits"]["hits"]:
                hits.append({
                    "id": hit["_id"], "score": hit["_score"], **hit["_source"]
                })

            total = result["hits"]["total"]["value"] if isinstance(result["hits"]["total"], dict) else result["hits"]["total"]
            return {"total": total, "hits": hits}
        except httpx.HTTPStatusError as e:
            logger.error(f"Search failed: status={e.response.status_code}, body={e.response.text}, query={body}")
            return {"total": 0, "hits": []}
        except Exception as e:
            logger.error(f"Search failed: {e}, query={body}")
            return {"total": 0, "hits": []}
    
    async def hybrid_search(
        self, index_name: str, query_vector: list[float], query_text: str, top_k: int = 10, filters: Dict | None = None, vector_weight: float = 0.7
    ) -> list[SearchResult]:
        text_weight = 1 - vector_weight
        
        query = {
            "bool": {
                "should": [
                    {
                        "knn": {
                            "field": "vector", "query_vector": query_vector, "k": top_k, "num_candidates": top_k * 2, "boost": vector_weight
                        }
                    }, {
                        "match": {
                            "content": {
                                "query": query_text, "boost": text_weight
                            }
                        }
                    }
                ]
            }
        }
        
        if filters:
            query["bool"]["filter"] = []
            for key, value in filters.items():
                query["bool"]["filter"].append({
                    "term": {key: value}
                })
        
        try:
            result = (await self._request("POST", f"/{index_name}/_search", json={
                "query": query, "size": top_k
            })).json()
            
            results = []
            for hit in result["hits"]["hits"]:
                results.append(SearchResult(
                    id=hit["_id"], score=hit["_score"], content=hit["_source"].get("content", ""), metadata=hit["_source"].get("metadata", {})
                ))
            
            return results
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []
    
    async def get_by_ids(self, index_name: str, doc_ids: list[str]) -> list[Dict]:
        try:
            result = (await self._request("POST", f"/{index_name}/_mget", json={"ids": doc_ids})).json()
            return [doc["_source"] for doc in result["docs"] if doc.get("found")]
        except Exception as e:
            logger.error(f"Failed to get documents by ids: {e}")
            return []

class VectorStoreFactory:
    """向量存储工厂"""
    
    _instances: dict[str, VectorStore] = {}
    
    @classmethod
    def get_store(cls, store_type: str = "elasticsearch") -> VectorStore:
        """获取向量存储实例"""
        if store_type not in cls._instances:
            if store_type == "elasticsearch":
                cls._instances[store_type] = ElasticsearchVectorStore()
            elif store_type == "qdrant":
                from .qdrant_store import QdrantVectorStore
                cls._instances[store_type] = QdrantVectorStore()
            else:
                raise StorageException(f"Unsupported vector store: {store_type}")
        return cls._instances[store_type]

def get_vector_store() -> VectorStore:
    """获取向量存储实例"""
    store_type = settings.vector_store.store_type
    return VectorStoreFactory.get_store(store_type)

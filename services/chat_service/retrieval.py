# -*- coding: utf-8 -*-
"""chat-service 知识库检索。

会话的 app_id 在当前前端里就是关联的知识库 ID。发送消息时先对用户问题做
embedding，再从向量库/MySQL 切片中召回参考内容，最后交给大模型回答。
"""
import os
from dataclasses import dataclass
from typing import Any

import httpx

from common.services.mysql_vector_search import MySQLVectorSearch
from common.storage.vector_store import get_vector_store
from common.utils import get_logger

DEFAULT_EMBEDDING_BASE_URL = os.getenv(
    "DEFAULT_EMBEDDING_BASE_URL",
    "http://114.242.210.44:6300/v1/embeddings",
)
DEFAULT_EMBEDDING_MODEL_NAME = os.getenv("DEFAULT_EMBEDDING_MODEL_NAME", "qwen3-embed-4b")
DEFAULT_EMBEDDING_API_KEY = os.getenv("LLM_API_KEY", "")

logger = get_logger("chat_retrieval")

@dataclass
class RetrievedChunk:
    """统一后的知识库召回结果。"""

    id: str
    score: float
    content: str
    doc_id: str = ""
    kb_id: str = ""
    source: str = ""
    metadata: dict[str, Any] | None = None

    def to_reference(self) -> dict[str, Any]:
        return {
            "chunk_id": self.id, "doc_id": self.doc_id, "kb_id": self.kb_id, "score": self.score, "source": self.source, "content": self.content, "metadata": self.metadata or {}, }

def _index_name(tenant_id: str, kb_id: str) -> str:
    return f"jusure_{tenant_id}_{kb_id}"

async def embed_query(text: str) -> list[float] | None:
    """调用 OpenAI 兼容 embedding 接口生成查询向量。"""
    if not text.strip():
        return None

    headers = {"Content-Type": "application/json"}
    if DEFAULT_EMBEDDING_API_KEY:
        headers["Authorization"] = f"Bearer {DEFAULT_EMBEDDING_API_KEY}"

    payload = {"model": DEFAULT_EMBEDDING_MODEL_NAME, "input": text}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                DEFAULT_EMBEDDING_BASE_URL, headers=headers, json=payload, )
            response.raise_for_status()
            data = response.json()

        items = data.get("data") or []
        if not items:
            logger.warning("embedding response has no data")
            return None
        vector = items[0].get("embedding")
        return vector if isinstance(vector, list) else None
    except Exception as exc:
        logger.warning(f"embedding query failed: {exc}")
        return None

async def _search_es(
    tenant_id: str, kb_id: str, query_vector: list[float], top_k: int, ) -> list[RetrievedChunk]:
    """优先从 Elasticsearch 的知识库向量索引召回。"""
    try:
        index = _index_name(tenant_id, kb_id)
        vector_store = get_vector_store()
        if not await vector_store.index_exists(index):
            return []

        result = await vector_store.search(
            index_name=index, query_vector=query_vector, top_k=top_k, )
        hits = result.get("hits", [])
        chunks: list[RetrievedChunk] = []
        for hit in hits:
            metadata = hit.get("metadata") or hit.get("chunk_metadata") or {}
            content = hit.get("content") or hit.get("content_with_weight") or ""
            if not content:
                continue
            chunks.append(
                RetrievedChunk(
                    id=str(hit.get("id") or hit.get("chunk_id") or ""), score=float(hit.get("score") or 0), content=str(content), doc_id=str(hit.get("doc_id") or metadata.get("doc_id") or ""), kb_id=str(hit.get("kb_id") or hit.get("knowledge_id") or kb_id), source="elasticsearch", metadata=metadata, )
            )
        return chunks
    except Exception as exc:
        logger.warning(f"ES retrieval failed: {exc}")
        return []

def _from_mysql_result(item: Any, source: str) -> RetrievedChunk:
    metadata = item.metadata or {}
    return RetrievedChunk(
        id=item.id, score=float(item.score or 0), content=item.content or "", doc_id=str(metadata.get("doc_id") or ""), kb_id=str(metadata.get("kb_id") or ""), source=source, metadata=metadata, )

async def retrieve_knowledge(
    tenant_id: str, kb_id: str, query: str, top_k: int = 5, ) -> list[RetrievedChunk]:
    """按 ES 向量 -> MySQL 向量 -> MySQL 文本的顺序召回知识库切片。"""
    tenant_id = str(tenant_id or "default")
    kb_id = str(kb_id or "").strip()
    if not kb_id:
        return []

    query_vector = await embed_query(query)
    if query_vector:
        es_chunks = await _search_es(tenant_id, kb_id, query_vector, top_k)
        if es_chunks:
            return es_chunks

        mysql_chunks = await MySQLVectorSearch().search(
            tenant_id=tenant_id, kb_ids=[kb_id], query_vector=query_vector, top_k=top_k, min_score=0.0, )
        if mysql_chunks:
            return [_from_mysql_result(item, "mysql_vector") for item in mysql_chunks]

    text_chunks = await MySQLVectorSearch().text_search(
        tenant_id=tenant_id, kb_ids=[kb_id], query_text=query, top_k=top_k, )
    return [_from_mysql_result(item, "mysql_text") for item in text_chunks]

def build_context_prompt(chunks: list[RetrievedChunk]) -> str:
    """把召回切片拼成给大模型的系统上下文。"""
    if not chunks:
        return (
            "当前会话已关联知识库，但没有检索到可用片段。"
            "如果用户问题需要知识库内容，请说明未检索到相关资料，并基于通用知识谨慎回答。"
        )

    blocks = []
    for idx, chunk in enumerate(chunks, 1):
        content = chunk.content.strip()
        if len(content) > 1200:
            content = content[:1200] + "..."
        blocks.append(
            f"[{idx}] chunk_id={chunk.id} doc_id={chunk.doc_id} score={chunk.score:.4f}\n{content}"
        )

    return (
        "你是知识库问答助手。请优先根据以下知识库检索结果回答；"
        "如果资料不足，明确说明不足，不要编造。\n\n"
        + "\n\n".join(blocks)
    )

def reference_docs(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    """从引用切片中提取文档级引用，供前端后续展示。"""
    docs: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not chunk.doc_id:
            continue
        docs.setdefault(
            chunk.doc_id, {"doc_id": chunk.doc_id, "kb_id": chunk.kb_id, "source": chunk.source}, )
    return list(docs.values())

# -*- coding: utf-8 -*-
"""
parser-service 业务层
- 切片（Chunk）CRUD
- 触发 Embedding 重跑
- 文档解析状态查询
- 文件摘要/标签/实体提取（LLM 调用）
- 文档 QA 对提取（LLM 调用）
- 文件分析（读取内容后 LLM 提取）
- 切片清洗任务管理
参考 ragflow api/apps/chunk_app.py + api/db/services/document_service.py
参考 jusure_AI ExtractAbstractFromFile / ExtractQaFromKnowledge / AnalyseFileView / DocClearTaskView
"""
import re
import uuid
from typing import Any

from sqlalchemy import select, and_

from common.models import db_manager, ChunkModel, DocumentModel, StatusEnum
from common.utils import get_logger, aembed_chunks, astore_chunks, EmbeddingModel
from common.utils.llm_client import call_llm_once
from common.config import settings

from .chunk_store import ChunkStore, _index_name

logger = get_logger("parser_service")

_chunk_store = ChunkStore()

# ---------------------------------------------------------------------------
# 切片查询
# ---------------------------------------------------------------------------

async def list_chunks(
    tenant_id: str, kb_id: str, doc_id: str | None = None, keyword: str | None = None, status: str | None = None, chunk_type: str | None = None, page: int = 1, page_size: int = 20, with_stats: bool = False, ) -> dict[str, Any]:
    """
    查询切片列表（向量库 + MySQL 元数据合并）
    返回与 RAGflow /datasets/{id}/documents/{doc_id}/chunks 对齐的字段结构
    支持 status 和 chunk_type 过滤，with_stats=True 时返回原文/自定义切片统计
    """
    # 从向量库获取切片列表
    result = await _chunk_store.list_chunks(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, keyword=keyword, status=status, chunk_type=chunk_type, page=page, page_size=page_size, with_stats=with_stats, )

    # 从 MySQL 批量获取元数据（important_keywords, page_num, position 等）
    chunk_ids = [hit.get("id") or hit.get("_id") for hit in result.get("chunks", [])]
    mysql_chunks: dict[str, ChunkModel] = {}
    if chunk_ids:
        async with db_manager.get_session() as session:
            stmt = select(ChunkModel).where(
                ChunkModel.id.in_(chunk_ids), ChunkModel.tenant_id == tenant_id
            )
            rows = await session.execute(stmt)
            for row in rows.all():
                chunk = row[0]
                mysql_chunks[chunk.id] = chunk

    # 合并向量库数据与 MySQL 元数据，对齐 RAGflow 字段名
    chunks = []
    for hit in result.get("chunks", []):
        chunk_id = hit.get("id") or hit.get("_id")
        mysql_chunk = mysql_chunks.get(chunk_id)

        # 默认值
        available = True
        page_num = None
        position = None
        important_keywords = []
        keyword_explanations = {}
        knowledge_points = []
        questions = []
        tag_kwd = []
        tag_feas = {}

        if mysql_chunk:
            # MySQL status: '1'=激活, '0'=删除
            available = mysql_chunk.status == StatusEnum.ACTIVE.value
            page_num = mysql_chunk.page_num
            position = mysql_chunk.position
            important_keywords = mysql_chunk.important_keywords or []
            keyword_explanations = mysql_chunk.keyword_explanations or {}
            # 知识点：为每个 item 补充 source 字段（兼容老数据）
            _chunk_type = mysql_chunk.chunk_type or "original"
            knowledge_points = [
                {**p, "source": p.get("source") or _chunk_type}
                for p in (mysql_chunk.knowledge_points or [])
            ]
            tag_kwd = mysql_chunk.chunk_metadata.get("tag_kwd", []) if mysql_chunk.chunk_metadata else []
            tag_feas = mysql_chunk.chunk_metadata.get("tag_feas", {}) if mysql_chunk.chunk_metadata else {}

        chunks.append({
            "id": chunk_id, "content": hit.get("content", ""), "content_with_weight": hit.get("content_with_weight", hit.get("content", "")), "document_id": doc_id or hit.get("doc_id", ""), "docnm_kwd": hit.get("docnm_kwd", ""), "important_keywords": important_keywords, "keyword_explanations": keyword_explanations, "knowledge_points": knowledge_points, "questions": questions, "dataset_id": kb_id, "image_id": hit.get("image_id", ""), "available": available, "positions": [position] if position else [], "page_num": page_num, "tag_kwd": tag_kwd, "tag_feas": tag_feas, "chunk_type": hit.get("chunk_type", mysql_chunk.chunk_type if mysql_chunk else "original"), # 向量库原始字段
            "doc_id": hit.get("doc_id", ""), "kb_id": hit.get("kb_id", kb_id), "metadata": hit.get("metadata", {}), })

    # 构建返回结果
    response = {
        "total": result.get("total", 0), "chunks": chunks, }
    
    # 如果需要统计信息，添加统计字段
    if with_stats and doc_id:
        stats = result.get("stats", {"original_count": 0, "custom_count": 0})
        response["original_count"] = stats.get("original_count", 0)
        response["custom_count"] = stats.get("custom_count", 0)

    # —— 前端测试 Mock 填充：切片/知识点为空时填充假数据（不落库） ——
    response = _fill_mock_for_frontend(response, kb_id=kb_id, doc_id=doc_id)

    return response

def _fill_mock_for_frontend(response: dict[str, Any], kb_id: str, doc_id: str | None) -> dict[str, Any]:
    """前端测试便利：若 chunks 为空或 chunk 的 knowledge_points 为空，填充 mock 数据。

    - 仅影响响应内容，不写入数据库/向量库
    - 通过字段 is_mock=True 标识 mock 数据，方便前端区分
    """
    chunks = response.get("chunks") or []

    # 构造一个 mock knowledge_points（两条，每条带 id、content、source）
    def _mock_points(chunk_source: str) -> list[dict[str, Any]]:
        return [
            {"id": "kp_mock_0001", "content": "【Mock】这是用于前端调试的示例知识点一", "source": chunk_source, "is_mock": True}, {"id": "kp_mock_0002", "content": "【Mock】这是用于前端调试的示例知识点二", "source": chunk_source, "is_mock": True}, ]

    if not chunks:
        # chunks 为空时，填充 3 条 mock 切片（original×2 + custom×1）
        mock_chunks = []
        for i, ctype in enumerate(["original", "original", "custom"], start=1):
            mock_chunks.append({
                "id": f"chunk_mock_{i:04d}", "content": f"【Mock】这是第 {i} 段示例切片内容，用于前端调试展示。", "content_with_weight": f"【Mock】这是第 {i} 段示例切片内容，用于前端调试展示。", "document_id": doc_id or "doc_mock_0001", "docnm_kwd": "Mock 示例文档.docx", "important_keywords": ["Mock关键词1", "Mock关键词2"], "keyword_explanations": {"Mock关键词1": "示例解释1", "Mock关键词2": "示例解释2"}, "knowledge_points": _mock_points(ctype), "questions": ["这是一个示例问题？"], "dataset_id": kb_id, "image_id": "", "available": True, "positions": [f"p{i}"], "page_num": i, "tag_kwd": [], "tag_feas": {}, "chunk_type": ctype, "doc_id": doc_id or "doc_mock_0001", "kb_id": kb_id, "metadata": {}, "is_mock": True, })
        response["chunks"] = mock_chunks
        response["total"] = len(mock_chunks)
        # 如存在统计字段则同步修正
        if "original_count" in response or "custom_count" in response:
            response["original_count"] = sum(1 for c in mock_chunks if c["chunk_type"] == "original")
            response["custom_count"] = sum(1 for c in mock_chunks if c["chunk_type"] == "custom")
    else:
        # 对每个真实 chunk，若 knowledge_points/important_keywords 为空，填充 mock
        for c in chunks:
            if not c.get("knowledge_points"):
                c["knowledge_points"] = _mock_points(c.get("chunk_type") or "original")
                c["is_mock_knowledge_points"] = True
            if not c.get("important_keywords"):
                c["important_keywords"] = ["Mock关键词1", "Mock关键词2"]
                c["is_mock_keywords"] = True

    return response

# ---------------------------------------------------------------------------
# 切片查询（含文档信息）
# ----------------------------------------------------------------------------

async def list_chunks_with_doc_info(
    tenant_id: str, kb_id: str, doc_id: str, keyword: str | None = None, status: str | None = None, chunk_type: str | None = None, page: int = 1, page_size: int = 20, with_stats: bool = True, ) -> dict[str, Any]:
    """
    查询切片列表（包含文档信息）
    返回结构：{total, chunks: [...], doc: {...}, original_count, custom_count}
    与 RAGflow /datasets/{id}/documents/{doc_id}/chunks 完全对齐
    """
    from common.models import DocumentModel

    # 获取切片列表
    chunks_result = await list_chunks(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, keyword=keyword, status=status, chunk_type=chunk_type, page=page, page_size=page_size, with_stats=with_stats, )

    # 获取文档信息
    doc_info = {}
    if doc_id:
        async with db_manager.get_session() as session:
            doc = await session.get(DocumentModel, doc_id)
            if doc:
                key_mapping = {
                    "chunk_num": "chunk_count", "kb_id": "dataset_id", "token_num": "token_count", "parser_id": "chunk_method", }
                run_mapping = {
                    "0": "UNSTART", "1": "RUNNING", "2": "CANCEL", "3": "DONE", "4": "FAIL", }
                doc_dict = doc.to_dict()
                renamed_doc = {}
                for key, value in doc_dict.items():
                    new_key = key_mapping.get(key, key)
                    renamed_doc[new_key] = value
                    if key == "run":
                        renamed_doc["run"] = run_mapping.get(str(value), value)
                doc_info = renamed_doc

    return {
        "total": chunks_result.get("total", 0), "chunks": chunks_result.get("chunks", []), "original_count": chunks_result.get("original_count", 0), "custom_count": chunks_result.get("custom_count", 0), "doc": doc_info, }

# ---------------------------------------------------------------------------

async def upsert_chunk(
    tenant_id: str, kb_id: str, doc_id: str, content: str | None = None, chunk_id: str | None = None, metadata: Dict | None = None, run_embedding: bool = True, available: bool | None = None, chunk_type: str = "original", ) -> dict[str, Any]:
    """
    新增或更新切片
    - 若 chunk_id 为 None 则新建
    - run_embedding=True 时调用 EmbeddingModel 生成向量后入库
    - available 控制切片启用状态
    - chunk_type: 切片类型 (original=原文切片, custom=自定义切片)
    """
    if not chunk_id:
        chunk_id = uuid.uuid4().hex

    status = StatusEnum.ACTIVE.value if available else StatusEnum.INACTIVE.value if available is not None else StatusEnum.ACTIVE.value
    doc = {
        "id": chunk_id, "doc_id": doc_id, "kb_id": kb_id, "tenant_id": tenant_id, "content": content, "metadata": metadata or {}, "status": status, "chunk_type": chunk_type, }

    if content and run_embedding:
        class _FakeChunk:
            def __init__(self):
                self.id = chunk_id
                self.content = content
                self.content_with_weight = content
                self.vector = None
                self.metadata = metadata or {}

        fake = _FakeChunk()
        model_path = settings.llm.default_embedding_model
        try:
            import asyncio
            await asyncio.wait_for(
                aembed_chunks([fake], model_path=model_path), timeout=30.0  # 最多等待 30 秒
            )
            if fake.vector:
                doc["vector"] = fake.vector
        except asyncio.TimeoutError:
            logger.warning(f"Embedding timeout for chunk {chunk_id}, skip vector")
        except Exception as e:
            logger.warning(f"Embedding failed for chunk {chunk_id}: {e}")

    await _chunk_store.upsert_chunk(tenant_id, kb_id, chunk_id, doc)

    async with db_manager.get_session() as session:
        existing = await session.get(ChunkModel, chunk_id)
        if existing:
            if content is not None:
                existing.content = content
            if metadata is not None:
                existing.chunk_metadata = metadata
            if available is not None:
                existing.status = status
        else:
            obj = ChunkModel(
                id=chunk_id, doc_id=doc_id, kb_id=kb_id, tenant_id=tenant_id, content=content or "", chunk_metadata=metadata or {}, status=status, chunk_type=chunk_type, )
            session.add(obj)
        await session.commit()

    return {"chunk_id": chunk_id, "doc_id": doc_id, "kb_id": kb_id, "chunk_type": chunk_type}

async def create_custom_chunk(
    tenant_id: str, kb_id: str, doc_id: str, content: str, available: bool = True, ) -> dict[str, Any]:
    """
    创建自定义切片（快捷接口）
    - chunk_type 固定为 "custom"
    - 自动生成向量
    - status 默认为启用
    """
    return await upsert_chunk(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, content=content, chunk_id=None, # 新建时自动生成
        metadata={}, run_embedding=True, available=available, chunk_type="custom", )

async def update_chunk_knowledge_point(
    tenant_id: str, kb_id: str, doc_id: str, chunk_id: str, action: str, point_id: str | None = None, content: str | None = None, ) -> dict[str, Any]:
    """编辑切片知识点（add/update/remove）。

    知识点结构：{"id": "kp_xxx", "content": "..."}
    存储于 chunk.knowledge_points 字段（JSON 数组）。
    """
    import uuid

    async with db_manager.get_session() as session:
        chunk = await session.get(ChunkModel, chunk_id)
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found")

        points: list[dict[str, Any]] = list(chunk.knowledge_points or [])
        action = (action or "").lower()
        affected_point: dict[str, Any] | None = None
        source = chunk.chunk_type or "original"  # 知识点来源（所属切片类型）

        if action == "add":
            new_id = f"kp_{uuid.uuid4().hex[:16]}"
            affected_point = {"id": new_id, "content": content or "", "source": source}
            points.append(affected_point)
        elif action == "update":
            found = False
            for p in points:
                if p.get("id") == point_id:
                    p["content"] = content or ""
                    # 补充 source（兼容老数据）
                    if not p.get("source"):
                        p["source"] = source
                    affected_point = p
                    found = True
                    break
            if not found:
                raise ValueError(f"Knowledge point {point_id} not found")
        elif action == "remove":
            before = len(points)
            points = [p for p in points if p.get("id") != point_id]
            if len(points) == before:
                raise ValueError(f"Knowledge point {point_id} not found")
            affected_point = {"id": point_id}
        else:
            raise ValueError(f"Unknown action: {action}")

        chunk.knowledge_points = points
        # SQLAlchemy JSON 字段原地修改需标记为已变更
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(chunk, "knowledge_points")
        await session.commit()

    return {
        "chunk_id": chunk_id, "action": action, "point": affected_point, "knowledge_points": points, "total": len(points), }

# 保留旧函数名作为兼容（转发到新逻辑）
async def update_chunk_keyword(
    tenant_id: str, kb_id: str, doc_id: str, chunk_id: str, keyword: str = "", action: str = "add", explanation: str | None = None, ) -> dict[str, Any]:
    """兼容旧版 API，内部调用新的 update_chunk_knowledge_point。
    旧 keyword+explanation 拼接为 content。
    """
    content = explanation if explanation else keyword
    return await update_chunk_knowledge_point(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, chunk_id=chunk_id, action=action, point_id=None, content=content, )

async def switch_chunks(
    tenant_id: str, kb_id: str, chunk_ids: list[str], available: bool, ) -> dict[str, Any]:
    """批量切换切片启用状态"""
    status = StatusEnum.ACTIVE.value if available else StatusEnum.INACTIVE.value
    updated = []

    async with db_manager.get_session() as session:
        for chunk_id in chunk_ids:
            chunk = await session.get(ChunkModel, chunk_id)
            if chunk:
                chunk.status = status
                updated.append(chunk_id)
        await session.commit()

    for chunk_id in updated:
        await _chunk_store.upsert_chunk(tenant_id, kb_id, chunk_id, {"status": status})

    return {"updated": updated, "available": available, "count": len(updated)}

async def delete_chunk(tenant_id: str, kb_id: str, chunk_id: str) -> bool:
    """删除切片（向量库 + MySQL）"""
    await _chunk_store.delete_chunk(tenant_id, kb_id, chunk_id)
    async with db_manager.get_session() as session:
        obj = await session.get(ChunkModel, chunk_id)
        if obj:
            obj.status = "-1"
            await session.commit()
    return True

# ---------------------------------------------------------------------------
# Embedding 重跑
# ---------------------------------------------------------------------------

async def re_embed_document(
    tenant_id: str, kb_id: str, doc_id: str, model_path: str | None = None, ) -> dict[str, Any]:
    """
    重新对指定文档的所有切片跑 Embedding 并写入向量库
    参考 ragflow KnowledgeEmbeddingsView (POST /ai/knowledge/embeddings)
    """
    effective_model = model_path or settings.llm.default_embedding_model

    # 从 MySQL 加载切片
    async with db_manager.get_session() as session:
        stmt = select(ChunkModel).where(
            and_(
                ChunkModel.doc_id == doc_id, ChunkModel.kb_id == kb_id, ChunkModel.tenant_id == tenant_id, ChunkModel.status != "-1", )
        )
        result = await session.execute(stmt)
        chunks = result.scalars().all()

    if not chunks:
        return {"doc_id": doc_id, "chunk_count": 0, "status": "no_chunks"}

    # 构造 fake-chunk 列表（与 aembed_chunks 接口对齐）
    class _FC:
        def __init__(self, c):
            self.id = c.id
            self.content = c.content or ""
            self.vector = None
            self.metadata = c.metadata or {}

    fakes = [_FC(c) for c in chunks]

    try:
        token_count, vector_size = await aembed_chunks(fakes, model_path=effective_model)
        logger.info(f"Re-embedded {len(fakes)} chunks for doc {doc_id}, tokens={token_count}")
    except Exception as e:
        logger.error(f"re_embed_document error: {e}")
        return {"doc_id": doc_id, "chunk_count": len(fakes), "status": "failed", "error": str(e)}

    # 批量写向量库
    index = _index_name(tenant_id, kb_id)
    try:
        await astore_chunks(fakes, index_name=index)
    except Exception as e:
        logger.error(f"astore_chunks error: {e}")
        return {"doc_id": doc_id, "chunk_count": len(fakes), "status": "store_failed", "error": str(e)}

    return {
        "doc_id": doc_id, "chunk_count": len(fakes), "token_count": token_count, "vector_size": vector_size, "status": "completed", }

# ---------------------------------------------------------------------------
# 文档解析状态
# ---------------------------------------------------------------------------

async def get_doc_state(
    tenant_id: str, kb_id: str, doc_id: str, ) -> dict[str, Any] | None:
    """
    查询文档解析阶段状态
    对应 jusure_AI KnowledgeFileStateView GET /ai/knowledge/file/state
    参考 ragflow DocumentService 中 progress / progress_msg 字段
    """
    async with db_manager.get_session() as session:
        stmt = select(DocumentModel).where(
            and_(
                DocumentModel.id == doc_id, DocumentModel.kb_id == kb_id, DocumentModel.tenant_id == tenant_id, )
        )
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            return None

        # 解析阶段映射（参考 ragflow TaskStatus + progress 字段语义）
        stage = "pending"
        if doc.status == "parsing":
            stage = "parsing"
        elif doc.status == "completed":
            stage = "done" if doc.progress >= 1.0 else "embedding"
        elif doc.status == "failed":
            stage = "failed"

        return {
            "document_id": doc.id, "doc_name": doc.name, "status": doc.status, "stage": stage, "progress": round(doc.progress * 100, 1), "progress_msg": doc.progress_msg, "chunk_num": doc.chunk_num, "token_num": doc.token_num, }

async def get_doc_detail(
    tenant_id: str, kb_id: str, doc_id: str, ) -> dict[str, Any] | None:
    """
    文档详情（包含切片列表简览）
    对应 jusure_AI KnowledgeDocDetailView GET /ai/knowledge/doc/detail
    """
    state = await get_doc_state(tenant_id, kb_id, doc_id)
    if not state:
        return None

    # 附加切片数量（向量库中实际数量）
    chunk_result = await _chunk_store.list_chunks(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, page=1, page_size=1, )
    state["chunk_num_in_vs"] = chunk_result.get("total", 0)
    return state

# ---------------------------------------------------------------------------
# 高优先级新增：批量操作 / 全量切片 / 含文档信息的切片列表
# ---------------------------------------------------------------------------

async def bulk_chunks(
    tenant_id: str, kb_id: str, doc_id: str, action: str, chunks: list[dict[str, Any]], ) -> dict[str, Any]:
    """切片批量操作（对应 jusure_AI KnowledgeDocChunkBulk POST /ai/chunk/bulk/do）

    action: "add" | "delete" | "update"
    每个 chunk 格式：{ content, chunk_id(update/delete时), metadata }
    """
    success_ids: list[str] = []
    failed: list[Dict] = []

    for item in chunks:
        try:
            content = item.get("content", "")
            chunk_id = item.get("chunk_id")
            metadata = item.get("metadata", {})

            if action == "delete":
                if not chunk_id:
                    failed.append({"item": item, "reason": "chunk_id required for delete"})
                    continue
                await _chunk_store.delete_chunk(tenant_id, kb_id, chunk_id)
                success_ids.append(chunk_id)
            elif action in ("add", "update"):
                result = await upsert_chunk(
                    tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, content=content, chunk_id=chunk_id if action == "update" else None, metadata=metadata, run_embedding=True, )
                success_ids.append(result.get("chunk_id", ""))
            else:
                failed.append({"item": item, "reason": f"unknown action: {action}"})
        except Exception as e:
            failed.append({"item": item, "reason": str(e)})

    return {
        "action": action, "success_count": len(success_ids), "success_ids": success_ids, "failed_count": len(failed), "failed": failed, }

async def list_all_chunks(
    tenant_id: str, kb_id: str, doc_id: str, ) -> dict[str, Any]:
    """获取文档全部切片（不分页），对应 jusure_AI KnowledgeDocBatch GET /ai/knowledge/doc/chunk/all"""
    # 先查总数
    first_page = await _chunk_store.list_chunks(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, page=1, page_size=1, )
    total = first_page.get("total", 0)
    if total == 0:
        return {"data_list": [], "total": 0}

    # 一次性拉取全部（上限 5000，防止 OOM）
    max_size = min(total, 5000)
    result = await _chunk_store.list_chunks(
        tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, page=1, page_size=max_size, )
    return {"data_list": result.get("chunks", []), "total": total}

# ---------------------------------------------------------------------------
# LLM 调用辅助
# ---------------------------------------------------------------------------

# 摘要/标签/实体 提示词（与 jusure_AI prompt_template/knowledge.py 完全对齐）
_ABSTRACT_PROMPT = """
## 角色
- 你是一位经验丰富的内容策展人，也是一位精通自然语言处理的文本总结专家。

## 目标
从给定的长文本中生成一份**精确、简洁且连贯的摘要**。

## 注意事项
- 摘要应全面忠实于原文，简洁连贯，字数控制在200-300字以内。

## 工作流
1. 仔细阅读原文，理解主题、关键论点、重要发现。
2. 提炼核心信息，压缩次要细节。
3. 组织并审校，确保连贯可读。

- 文本如下：
----------------------------------------
{text}
----------------------------------------
- 仅返回摘要文本：
""".strip()

_TAG_PROMPT = """
## 角色
- 你是一位专注于文本分析和信息提取的专家，擅长从复杂文本中提取关键词标签。

## 目标
从长文本中提取出最核心的关键词和主题标签（不超过30个，按重要性排序）。

## 输出格式
- 输出应为一组关键词或主题标签，以逗号分隔。

- 文本如下：
----------------------------------------
{text}
----------------------------------------
- 仅返回结果数据：
""".strip()

_ENTITY_PROMPT = """
## 角色
- 你是一位专注于文本分析和信息提取的专家，擅长识别文本中的关键实体。

## 目标
从长文本中提取出最核心的实体（不超过30个）。

## 输出格式
- 输出应为一组关键词或主题标签，以逗号分隔。

- 文本如下：
----------------------------------------
{text}
----------------------------------------
- 仅返回结果数据：
""".strip()

_QA_PROMPT = """
给定以下文本和关键词，请严格基于"文本"内容，按照指定关键词的语义相关范围，从文本中提取与关键词有明确语义关联的问题和答案（如未指定关键词则从全文中提取）。再从答案中提取问题要点/关键词（多个词用、连接），并将它们组织成多个结构化的问答对。每个问答对应清晰标识，并使用以下格式（每个问答对用"$delimiter$"拼接）：

问题: <问题>
答案: <答案>
问题要点: <答案关键词1、答案关键词2、 ...>

## 要求：
- 仅基于"文本"内容提取问答对，禁止从"示例"或"关键词"本身生成问题和答案；
- 每一组问答对之间必须用$delimiter$分隔；
- 仅返回与指定关键词有明确语义关联的问题和答案及要点，参考示例格式，不要返回其他内容；
- 如果没有符合条件的内容，仅返回空字符串""，不要输出任何解释或说明。

## 关键词：
```{key_words}```

## 文本内容：
{text}
""".strip()

# ---------------------------------------------------------------------------
# 文件内容读取辅助（从 MinIO 读取文本）
# ---------------------------------------------------------------------------

async def _read_file_text(file_url: str) -> str:
    """
    从 MinIO / OSS 读取文件内容并返回文本
    支持 .txt / .md 直接 decode；其余格式尝试 UTF-8 decode
    参考 jusure_AI KnowledgeController.document_splitter_v1
    参考 ragflow deepdoc/parser 解析器体系（此处简化为读取原始文本）
    """
    try:
        from common.storage import get_file_store
        fs = get_file_store()
        raw = await fs.get(file_url)
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"_read_file_text error for {file_url}: {e}")
        return ""

def _split_qa_result(full_result: str) -> list[dict[str, str]]:
    """
    解析 LLM 输出的 QA 文本（$delimiter$ 分隔）
    对应 jusure_AI ExtractQaFromKnowledge.split_qa
    """
    qa_list = []
    full_result = full_result.replace("\n", "")
    for item in full_result.split("$delimiter$"):
        cleaned = re.sub(r"<think>.*?</think>", "", item, flags=re.DOTALL)
        result = re.findall(r"问题: (.*?)答案: (.*?)问题要点: (.+)", cleaned)
        if result:
            find = result[0]
            qa_list.append({
                "question": find[0].strip(), "answer": find[1].strip(), "answer_keywords": find[2].strip(), })
    return qa_list

# ---------------------------------------------------------------------------
# 文件摘要/标签/实体 提取
# POST /ai/file/extract/abstract
# 对应 jusure_AI ExtractAbstractFromFile POST /ai/file/extract/abstract
# ---------------------------------------------------------------------------

async def extract_abstract(
    tenant_id: str, file: str | None = None, content: str | None = None, model_id: str | None = None, type_keys: list[str] | None = None, return_content: bool = False, mm_prompt: str | None = None, ) -> dict[str, Any]:
    """
    从文件 URL 或直接文本中提取摘要/标签/实体。

    参数：
      file        — MinIO 对象路径，若提供则先读取文本内容
      content     — 直接传入的文本内容（优先级高于 file）
      model_id    — 指定 AI 模型 ID（可选）
      type_keys   — 提取类型列表，可含 'abstract'/'tag'/'entity'，默认 ['abstract']
      return_content — 是否在响应中返回原始文本
      mm_prompt   — 自定义解析提示词（用于 file 解析阶段，暂保留字段）

    逻辑：
      1. 若 content 为空且传入 file，则从 MinIO 读取文件文本（对齐 jusure_AI 逻辑）
      2. 对每个 type_key 分别调用 LLM 提取
    """
    if type_keys is None:
        type_keys = ["abstract"]

    # 读取文件内容
    if not content and file:
        content = await _read_file_text(file)

    ret: dict[str, Any] = {k: "" for k in type_keys}
    if return_content:
        ret["content"] = content or ""

    if not content:
        return ret

    prompt_map = {
        "abstract": _ABSTRACT_PROMPT, "tag": _TAG_PROMPT, "entity": _ENTITY_PROMPT, }

    for key in type_keys:
        tmpl = prompt_map.get(key)
        if not tmpl:
            continue
        try:
            message = tmpl.format(text=content)
            ret[key] = await call_llm_once(
                [{"role": "user", "content": message}], model_id=model_id, tenant_id=tenant_id, )
        except Exception as e:
            logger.error(f"extract_abstract [{key}] error: {e}")
            ret[key] = ""

    return ret

# ---------------------------------------------------------------------------
# 文档 QA 对提取
# POST /ai/knowledge/doc/extract/qa
# 对应 jusure_AI ExtractQaFromKnowledge POST /ai/knowledge/doc/extract/qa
# ---------------------------------------------------------------------------

async def extract_doc_qa(
    tenant_id: str, knowledge_ids: list[str], model_id: str, key_words: str = "", ) -> list[dict[str, Any]]:
    """
    从知识库下的文档中提取 QA 问答对。

    逻辑：
      1. 遍历 knowledge_ids，查询每个知识库下的文档列表
      2. 读取文档文本内容（从 MinIO）
      3. 调用 LLM 提取 QA，并解析 $delimiter$ 分隔格式
      4. 跨文档去重（相同 question 跳过）
    对应 jusure_AI ExtractQaFromKnowledge，去掉了 MongoDB extract_id 依赖，
    改为纯 MySQL + MinIO 实现。
    """
    from sqlalchemy import select, and_
    from common.models import db_manager, DocumentModel, KnowledgeModel

    extract_result: list[dict[str, Any]] = []
    seen_questions: dict[str, set] = {}

    for knowledge_id in knowledge_ids:
        async with db_manager.get_session() as session:
            stmt = select(DocumentModel).where(
                and_(
                    DocumentModel.kb_id == knowledge_id, DocumentModel.tenant_id == tenant_id, DocumentModel.status != "-1", )
            )
            docs = (await session.execute(stmt)).scalars().all()

        for doc in docs:
            doc_id = doc.id
            doc_name = doc.name or ""
            file_url = doc.location or ""

            try:
                text = await _read_file_text(file_url)
                if not text:
                    extract_result.append({
                        "document_id": doc_id, "knowledge_id": knowledge_id, "doc_name": doc_name, "qa_list": [], "status": 0, "message": "文件内容为空", })
                    continue

                prompt = _QA_PROMPT.format(text=text, key_words=key_words or "")
                full_result = await call_llm_once(
                    [{"role": "user", "content": prompt}], model_id=model_id, tenant_id=tenant_id, )
                qa_list = _split_qa_result(full_result)

                # 跨文档去重
                seen = seen_questions.setdefault(knowledge_id, set())
                dedup_qa: list[Dict] = []
                for qa in qa_list:
                    q = qa.get("question", "").strip()
                    if q and q not in seen:
                        seen.add(q)
                        dedup_qa.append(qa)

                extract_result.append({
                    "document_id": doc_id, "knowledge_id": knowledge_id, "doc_name": doc_name, "qa_list": dedup_qa, "status": 1, "message": "提取成功", })
            except Exception as e:
                logger.error(f"extract_doc_qa error doc={doc_id}: {e}")
                extract_result.append({
                    "document_id": doc_id, "knowledge_id": knowledge_id, "doc_name": doc_name, "qa_list": [], "status": 0, "message": f"提取失败: {str(e)}", })

    return extract_result

# ---------------------------------------------------------------------------
# 文件分析
# POST /ai/file/analyse
# 对应 jusure_AI AnalyseFileView POST /ai/file/analyse（在 flow.py）
# ---------------------------------------------------------------------------

async def analyse_file(
    tenant_id: str, files: list[str], prompt_list: str | None = None, model_id: str | None = None, ) -> str:
    """
    读取文件文本内容，使用自定义提示词（或默认提示词）分析文件。

    逻辑：
      1. 读取 files[0] 的文本内容（与 jusure_AI AnalyseFileView 保持一致，仅处理第一个文件）
      2. 若传入 prompt_list，将其作为 system 角色提示词
      3. 返回 LLM 输出文本
    参考 jusure_AI flow.py AnalyseFileView + KnowledgeController.document_splitter_v1
    ragflow 方案：通过 deepdoc/parser 解析 PDF/DOCX，此处简化为文本读取，
    未来可集成 ragflow 解析器链路。
    """
    if not files:
        return ""

    content = await _read_file_text(files[0])
    if not content:
        return ""

    messages: list[Dict] = []
    if prompt_list:
        messages.append({"role": "system", "content": prompt_list})
    messages.append({"role": "user", "content": content})

    try:
        return await call_llm_once(messages, model_id=model_id, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"analyse_file error: {e}")
        raise

# ---------------------------------------------------------------------------
# 切片清洗任务管理
# POST/GET /ai/document/clear/task
# GET /ai/document/clear/data
# 对应 jusure_AI DocClearTaskView + DocClearDataView
#
# 设计说明：
# jusure_AI 依赖 Celery 异步任务（async_document_chunk_clear.delay）+ MongoDB 存储清洗数据。
# 微服务版本改为：
#   - 任务写入 MySQL TaskModel（与 task-executor 体系对齐）
#   - 清洗数据存入 MySQL ChunkClearModel（新增简化版）
# 若尚无 ChunkClearModel，降级为内存返回（接口结构对齐，后续迭代补全持久化）。
# ---------------------------------------------------------------------------

async def create_clear_task(
    tenant_id: str, knowledge_id: str, doc_ids: list[str], model_id: str, chunk_ids: list[str] | None = None, rule_ids: list[str] | None = None, call_words: str | None = None, ) -> dict[str, Any]:
    """
    创建切片清洗任务，推送到 task-executor 队列。
    对应 jusure_AI DocClearTaskView POST /ai/document/clear/task

    实现策略：
      在 MySQL TaskModel 写入一条 type='chunk_clear' 任务记录，
      由 task-executor Worker 消费并执行切片清洗逻辑。
    """
    from sqlalchemy import select, and_
    from common.models import db_manager, DocumentModel

    task_id = uuid.uuid4().hex

    # 写入任务记录（依赖 task-executor TaskModel）
    try:
        from common.models.models import TaskModel
        async with db_manager.get_session() as session:
            task = TaskModel(
                id=task_id, tenant_id=tenant_id, kb_id=knowledge_id, task_type="chunk_clear", status="pending", payload={
                    "knowledge_id": knowledge_id, "doc_ids": doc_ids, "chunk_ids": chunk_ids or [], "rule_ids": rule_ids or [], "call_words": call_words or "", "model_id": model_id, }, progress=0.0, )
            session.add(task)
            await session.commit()
        logger.info(f"create_clear_task: task_id={task_id}, doc_ids={doc_ids}")
    except Exception as e:
        logger.warning(f"create_clear_task DB write failed (TaskModel may not exist): {e}")

    return {"task_id": task_id}

async def get_clear_task_progress(task_id: str) -> dict[str, Any]:
    """
    查询切片清洗任务进度。
    对应 jusure_AI DocClearTaskView GET /ai/document/clear/task

    返回结构与 jusure_AI 对齐：
      { state, current, total, success, doc_info }
    """
    try:
        from common.models.models import TaskModel
        from common.models import db_manager
        async with db_manager.get_session() as session:
            task = await session.get(TaskModel, task_id)
            if not task:
                return {"state": "PENDING", "current": 0, "total": 0, "success": 0, "doc_info": None}
            progress_info = task.payload or {}
            return {
                "state": task.status.upper() if task.status else "PENDING", "current": progress_info.get("current", 0), "total": progress_info.get("total", 0), "success": progress_info.get("success", 0), "doc_info": progress_info, }
    except Exception as e:
        logger.warning(f"get_clear_task_progress error: {e}")
        return {"state": "PENDING", "current": 0, "total": 0, "success": 0, "doc_info": None}

async def get_clear_data(task_id: str) -> list[dict[str, Any]]:
    """
    查询切片清洗数据列表（清洗后的切片内容）。
    对应 jusure_AI DocClearDataView GET /ai/document/clear/data

    当前实现：查询向量库中 task_id 关联的切片（通过 metadata.clear_task_id 标记）
    若无记录则返回空列表。
    """
    try:
        from common.storage import get_vector_store
        vs = get_vector_store()
        results = vs.search(
            index="jusure_chunk_clear", query={"bool": {"must": [{"term": {"clear_task_id": task_id}}]}}, size=200, from_=0, )
        return results.get("hits", [])
    except Exception as e:
        logger.warning(f"get_clear_data error: {e}")
        return []
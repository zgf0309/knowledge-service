# -*- coding: utf-8 -*-
"""
parser-service 路由
对外接口与 jusure_AI 对齐：
  GET  /ai/knowledge/doc/chunk       — 切片列表
  POST /ai/knowledge/doc/chunk/edit  — 新增/修改切片
  DELETE /ai/knowledge/doc/chunk     — 删除切片
  POST /ai/knowledge/embeddings      — 触发重跑 Embedding
  GET  /ai/knowledge/file/state      — 文档解析阶段状态
  GET  /ai/knowledge/doc/detail      — 文档详情（含切片数量）
"""
from typing import Any

from fastapi import APIRouter, Query, Body, HTTPException, Depends
from pydantic import BaseModel, Field

from common.auth_context import get_current_request_context, get_request_context, pick_tenant
from common.utils import get_logger
from common.utils.response import api_error, api_success

from . import services as svc

logger = get_logger("parser_api")
router = APIRouter(prefix="/ai", tags=["Parser Service"], dependencies=[Depends(get_request_context)])

def current_tenant() -> str:
    return pick_tenant(get_current_request_context())

# ---------------------------------------------------------------------------
# Pydantic 请求体
# ---------------------------------------------------------------------------
class ChunkEditRequest(BaseModel):
    """"新增/编辑切片请求（对齐 jusure_AI KnowledgeDocumentChunkEditView）"""
    knowledge_id: str = Field(..., description="知识库ID")
    document_id: str = Field(..., description="文档ID")
    chunk_id: str | None = Field(None, description="切片ID，空则新建")
    content: str | None = Field(None, description="切片内容")
    metadata: dict[str, Any] | None = Field(default_factory=dict)
    run_embedding: bool = Field(default=True, description="是否重新生成向量")
    available: bool | None = Field(None, description="是否启用该切片（true=启用，false=禁用）")

class ChunkKeywordRequest(BaseModel):
    """编辑切片知识点请求"""
    knowledge_id: str = Field(..., description="知识库ID")
    document_id: str = Field(..., description="文档ID")
    chunk_id: str = Field(..., description="切片ID")
    action: str = Field(..., description="操作：add 新增知识点，update 更新知识点，remove 删除知识点")
    point_id: str | None = Field(None, description="知识点ID（update/remove 时必填）")
    content: str | None = Field(None, description="知识点内容（add/update 时必填）")

class ChunkSwitchRequest(BaseModel):
    """批量切换切片启用状态请求"""
    knowledge_id: str = Field(..., description="知识库ID")
    chunk_ids: list[str] = Field(..., description="切片ID列表")
    available: bool = Field(..., description="目标状态：true=启用，false=禁用")

class CreateCustomChunkRequest(BaseModel):
    """新增自定义切片请求"""
    knowledge_id: str = Field(..., description="知识库ID")
    document_id: str = Field(..., description="文档ID")
    content: str = Field(..., min_length=1, description="切片内容")
    available: bool = Field(default=True, description="是否启用该切片，默认启用")

class EmbeddingRequest(BaseModel):
    """触发 Embedding 重跑（对齐 jusure_AI KnowledgeEmbeddingsView）"""
    knowledge_id: str
    document_id: str
    aigc_model_id: str | None = Field(None, description="嵌入模型ID，可覆盖默认值")

# ---------------------------------------------------------------------------
# GET /ai/knowledge/doc/chunk — 切片列表
# 对应 jusure_AI KnowledgeDocumentChunkView GET
# 参考 ragflow chunk_app.list_chunk
# ---------------------------------------------------------------------------
@router.get("/knowledge/doc/chunk")
@router.get("/knowledge/chunk", include_in_schema=False)  # 别名路由
async def list_chunks(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), document_id: str | None = Query(None), query: str | None = Query(None, description="切片内容模糊搜索关键词"), status: str | None = Query(None, description="状态过滤: 1=启用, 0=禁用"), chunk_type: str | None = Query(None, description="切片类型: original=原文切片, custom=自定义切片"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), ):
    """
    查询切片列表（支持模糊检索、状态过滤、切片类型过滤，分页）
    - query: 切片内容模糊搜索
    - status: 状态过滤 (1=启用, 0=禁用)
    - chunk_type: 类型过滤 (original=原文切片, custom=自定义切片)
    - 返回 original_count(原文切片数) 和 custom_count(自定义切片数)
    """
    try:
        tenant_id = current_tenant()
        # 状态映射: 前端 1/0 -> 向量库 status
        es_status = None
        if status is not None:
            es_status = status  # 直接透传，由前端保证格式
        
        # 如果提供了 document_id，同时获取文档信息
        if document_id:
            result = await svc.list_chunks_with_doc_info(
                tenant_id=tenant_id, kb_id=knowledge_id, doc_id=document_id, keyword=query, status=es_status, chunk_type=chunk_type, page=page_no, page_size=page_size, with_stats=True, )
            return api_success(data={
                "total": result.get("total", 0), "original_count": result.get("original_count", 0), "custom_count": result.get("custom_count", 0), "chunks": result.get("chunks", []), "doc": result.get("doc", {})
            })
        else:
            result = await svc.list_chunks(
                tenant_id=tenant_id, kb_id=knowledge_id, doc_id=document_id, keyword=query, status=es_status, chunk_type=chunk_type, page=page_no, page_size=page_size, )
            return api_success(data=result)
    except Exception as e:
        logger.exception("list_chunks error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/knowledge/doc/chunk/edit — 新增/修改切片
# 对应 jusure_AI KnowledgeDocumentChunkEditView
# 参考 ragflow chunk_app.create / set
# ---------------------------------------------------------------------------
@router.post("/knowledge/doc/chunk/edit")
async def edit_chunk(
    tenant_id: str | None = Query("default"), body: ChunkEditRequest = Body(...), ):
    """新增或更新切片内容，可选重跑 Embedding"""
    try:
        tenant_id = current_tenant()
        result = await svc.upsert_chunk(
            tenant_id=tenant_id, kb_id=body.knowledge_id, doc_id=body.document_id, content=body.content, chunk_id=body.chunk_id, metadata=body.metadata, run_embedding=body.run_embedding, available=body.available, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("edit_chunk error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/knowledge/doc/chunk/custom — 新增自定义切片
# ---------------------------------------------------------------------------
@router.post("/knowledge/doc/chunk/custom")
async def create_custom_chunk(
    tenant_id: str | None = Query("default"), body: CreateCustomChunkRequest = Body(...), ):
    """
    新增自定义切片
    - chunk_type 固定为 "custom"
    - 自动生成向量
    - 状态默认为启用
    """
    try:
        tenant_id = current_tenant()
        result = await svc.create_custom_chunk(
            tenant_id=tenant_id, kb_id=body.knowledge_id, doc_id=body.document_id, content=body.content, available=body.available, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("create_custom_chunk error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/knowledge/doc/chunk/keyword — 编辑切片知识点
# ---------------------------------------------------------------------------
@router.post("/knowledge/doc/chunk/keyword")
async def edit_chunk_knowledge_point(
    tenant_id: str | None = Query("default"), body: ChunkKeywordRequest = Body(...), ):
    """编辑切片知识点（add/update/remove）。
    - add：新增知识点，需传 content，返回自动生成的 point_id
    - update：更新知识点，需传 point_id 和 content
    - remove：删除知识点，需传 point_id
    """
    try:
        tenant_id = current_tenant()
        action = (body.action or "").lower()
        if action == "add" and not body.content:
            return api_error(message="action=add 时 content 必填", code=400)
        if action == "update" and (not body.point_id or not body.content):
            return api_error(message="action=update 时 point_id 和 content 必填", code=400)
        if action == "remove" and not body.point_id:
            return api_error(message="action=remove 时 point_id 必填", code=400)

        result = await svc.update_chunk_knowledge_point(
            tenant_id=tenant_id, kb_id=body.knowledge_id, doc_id=body.document_id, chunk_id=body.chunk_id, action=action, point_id=body.point_id, content=body.content, )
        return api_success(data=result)
    except ValueError as e:
        return api_error(message=str(e), code=404)
    except Exception as e:
        logger.exception("edit_chunk_knowledge_point error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# PUT /ai/knowledge/doc/chunk/switch — 批量切换切片启用状态
# ---------------------------------------------------------------------------
@router.put("/knowledge/doc/chunk/switch")
async def switch_chunks(
    tenant_id: str | None = Query("default"), body: ChunkSwitchRequest = Body(...), ):
    """批量切换切片启用状态"""
    try:
        tenant_id = current_tenant()
        result = await svc.switch_chunks(
            tenant_id=tenant_id, kb_id=body.knowledge_id, chunk_ids=body.chunk_ids, available=body.available, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("switch_chunks error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# DELETE /ai/knowledge/doc/chunk — 删除切片
# 参考 ragflow chunk_app.rm
# ---------------------------------------------------------------------------
@router.delete("/knowledge/doc/chunk")
async def delete_chunk(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), chunk_id: str = Query(...), ):
    """删除切片（向量库 + MySQL 逻辑删除）"""
    try:
        tenant_id = current_tenant()
        await svc.delete_chunk(tenant_id, knowledge_id, chunk_id)
        return api_success(message="删除成功")
    except Exception as e:
        logger.exception("delete_chunk error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/knowledge/embeddings — 触发 Embedding 重跑
# 对应 jusure_AI KnowledgeEmbeddingsView POST /ai/knowledge/embeddings
# ---------------------------------------------------------------------------
@router.post("/knowledge/embeddings")
async def run_embeddings(
    tenant_id: str | None = Query("default"), body: EmbeddingRequest = Body(...), ):
    """对指定文档的所有切片重新运行 Embedding"""
    try:
        tenant_id = current_tenant()
        result = await svc.re_embed_document(
            tenant_id=tenant_id, kb_id=body.knowledge_id, doc_id=body.document_id, model_path=body.aigc_model_id, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("run_embeddings error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/knowledge/file/state — 文档解析阶段状态
# 对应 jusure_AI KnowledgeFileStateView GET /ai/knowledge/file/state
# ---------------------------------------------------------------------------
@router.get("/knowledge/file/state")
async def get_file_state(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), document_id: str = Query(...), ):
    """查询文档解析阶段（pending/parsing/embedding/done/failed）"""
    try:
        tenant_id = current_tenant()
        state = await svc.get_doc_state(tenant_id, knowledge_id, document_id)
        if state is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return api_success(data=state)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_file_state error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/knowledge/doc/detail — 文档详情
# 对应 jusure_AI KnowledgeDocDetailView GET /ai/knowledge/doc/detail
# ---------------------------------------------------------------------------
@router.get("/knowledge/doc/detail")
async def get_doc_detail(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), document_id: str = Query(...), ):
    """文档详情（解析结果 + 切片数量）"""
    try:
        tenant_id = current_tenant()
        detail = await svc.get_doc_detail(tenant_id, knowledge_id, document_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return api_success(data=detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_doc_detail error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# 高优先级新增接口
# ---------------------------------------------------------------------------

class BulkChunkRequest(BaseModel):
    """切片批量操作请求（对应 jusure_AI KnowledgeDocChunkBulk POST /ai/chunk/bulk/do）"""
    knowledge_id: str
    document_id: str
    action: str = Field("add", description="操作类型: add / delete / update")
    chunks: list[dict[str, Any]] = Field(default_factory=list, description="切片列表")

@router.post("/chunk/bulk/do", tags=["Parser Service"])
async def bulk_chunks(
    tenant_id: str | None = Query("default"), body: BulkChunkRequest = Body(...), ):
    """切片批量操作（新增/删除/更新），对应 jusure_AI KnowledgeDocChunkBulk POST /ai/chunk/bulk/do"""
    try:
        tenant_id = current_tenant()
        result = await svc.bulk_chunks(
            tenant_id=tenant_id, kb_id=body.knowledge_id, doc_id=body.document_id, action=body.action, chunks=body.chunks, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("bulk_chunks error")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/knowledge/doc/chunk/all")
async def list_all_chunks(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), document_id: str = Query(...), ):
    """获取文档全部切片（不分页），对应 jusure_AI KnowledgeDocBatch GET /ai/knowledge/doc/chunk/all"""
    try:
        tenant_id = current_tenant()
        result = await svc.list_all_chunks(
            tenant_id=tenant_id, kb_id=knowledge_id, doc_id=document_id, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("list_all_chunks error")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/knowledge/doc/chunk/list")
async def list_chunks_with_doc_info(
    tenant_id: str | None = Query("default"), knowledge_id: str = Query(...), document_id: str | None = Query(None), keyword: str | None = Query(None), chunk_id: str | None = Query(None), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), ):
    """切片列表（含文档信息），对应 jusure_AI KnowledgeDocumentChunkListView GET /ai/knowledge/doc/chunk/list"""
    try:
        tenant_id = current_tenant()
        result = await svc.list_chunks_with_doc_info(
            tenant_id=tenant_id, kb_id=knowledge_id, doc_id=document_id, keyword=keyword, chunk_id=chunk_id, page=page_no, page_size=page_size, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("list_chunks_with_doc_info error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# 待实现接口（中优先级）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /ai/file/extract/abstract — 文件摘要/标签/实体提取
# 对应 jusure_AI ExtractAbstractFromFile POST /ai/file/extract/abstract
# ---------------------------------------------------------------------------

class ExtractAbstractRequest(BaseModel):
    file: str | None = Field(None, description="MinIO 对象路径，与 content 二选一")
    content: str | None = Field(None, description="直接传入的文本内容")
    model_id: str | None = Field(None, description="AI 模型 ID")
    type_keys: list[str] | None = Field(
        default_factory=lambda: ["abstract"], description="提取类型: abstract / tag / entity，可多选", )
    return_content: bool = Field(default=False, description="是否在响应中返回原始文本")
    mm_prompt: str | None = Field(None, description="自定义文件解析提示词（保留字段）")

@router.post("/file/extract/abstract")
async def extract_abstract(
    tenant_id: str | None = Query("default"), body: ExtractAbstractRequest = Body(...), ):
    """
    从文件 URL 或直接文本中提取摘要/标签/实体（可多类型同时提取）。
    对应 jusure_AI ExtractAbstractFromFile POST /ai/file/extract/abstract
    """
    try:
        tenant_id = current_tenant()
        result = await svc.extract_abstract(
            tenant_id=tenant_id, file=body.file, content=body.content, model_id=body.model_id, type_keys=body.type_keys, return_content=body.return_content, mm_prompt=body.mm_prompt, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("extract_abstract error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/knowledge/doc/extract/qa — 从文档提取 QA 问答对
# 对应 jusure_AI ExtractQaFromKnowledge POST /ai/knowledge/doc/extract/qa
# ---------------------------------------------------------------------------

class ExtractDocQaRequest(BaseModel):
    knowledge_ids: str = Field(..., description="知识库 ID，多个用逗号分隔")
    aigc_model_id: str = Field(..., description="AI 模型 ID")
    key_words: str | None = Field(default="", description="关键词，多个用逗号分隔")

@router.post("/knowledge/doc/extract/qa")
async def extract_doc_qa(
    tenant_id: str | None = Query("default"), body: ExtractDocQaRequest = Body(...), ):
    """
    从知识库下的文档中提取 QA 问答对（含跨文档去重）。
    对应 jusure_AI ExtractQaFromKnowledge POST /ai/knowledge/doc/extract/qa
    """
    try:
        tenant_id = current_tenant()
        kb_ids = [k.strip() for k in body.knowledge_ids.split(", ") if k.strip()]
        result = await svc.extract_doc_qa(
            tenant_id=tenant_id, knowledge_ids=kb_ids, model_id=body.aigc_model_id, key_words=body.key_words or "", )
        return api_success(data={"extract_result": result, "total": len(result)})
    except Exception as e:
        logger.exception("extract_doc_qa error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/file/analyse — 文件分析（LLM 提取结构化内容）
# 对应 jusure_AI AnalyseFileView POST /ai/file/analyse（在 flow.py 中）
# ---------------------------------------------------------------------------

class AnalyseFileRequest(BaseModel):
    files: list[str] | None = Field(default_factory=list, description="文件链接列表（处理第一个）")
    prompt_list: str | None = Field(None, description="自定义 system 提示词")
    model_id: str | None = Field(None, description="AI 模型 ID（可选）")

@router.post("/file/analyse")
async def analyse_file(
    tenant_id: str | None = Query("default"), body: AnalyseFileRequest = Body(...), ):
    """
    读取文件内容，使用 LLM 分析并返回结构化文本。
    对应 jusure_AI AnalyseFileView POST /ai/file/analyse
    """
    try:
        tenant_id = current_tenant()
        if not body.files:
            raise HTTPException(status_code=400, detail="files 不能为空")
        result = await svc.analyse_file(
            tenant_id=tenant_id, files=body.files, prompt_list=body.prompt_list, model_id=body.model_id, )
        return api_success(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("analyse_file error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/document/clear/task — 创建切片清洗任务
# GET  /ai/document/clear/task — 查询清洗任务进度
# 对应 jusure_AI DocClearTaskView POST/GET /ai/document/clear/task
# ---------------------------------------------------------------------------

class DocClearTaskRequest(BaseModel):
    knowledge_id: str = Field(..., description="知识库 ID")
    doc_ids: list[str] = Field(..., description="文档 ID 列表")
    aigc_model_id: str = Field(..., description="AI 模型 ID")
    chunk_ids: list[str] | None = Field(default_factory=list, description="指定切片 ID 列表（可选）")
    rule_ids: list[str] | None = Field(default_factory=list, description="清洗规则 ID 列表（可选）")
    call_words: str | None = Field(None, description="触发词（可选）")

@router.post("/document/clear/task")
async def create_clear_task(
    tenant_id: str | None = Query("default"), body: DocClearTaskRequest = Body(...), ):
    """
    创建切片清洗任务，推送到 task-executor 队列异步执行。
    对应 jusure_AI DocClearTaskView POST /ai/document/clear/task
    """
    try:
        tenant_id = current_tenant()
        result = await svc.create_clear_task(
            tenant_id=tenant_id, knowledge_id=body.knowledge_id, doc_ids=body.doc_ids, model_id=body.aigc_model_id, chunk_ids=body.chunk_ids, rule_ids=body.rule_ids, call_words=body.call_words, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("create_clear_task error")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/document/clear/task")
async def get_clear_task_progress(
    task_id: str = Query(..., description="任务 ID"), ):
    """
    查询切片清洗任务进度（state / current / total / success）。
    对应 jusure_AI DocClearTaskView GET /ai/document/clear/task
    """
    try:
        tenant_id = current_tenant()
        result = await svc.get_clear_task_progress(task_id=task_id)
        return api_success(data=result)
    except Exception as e:
        logger.exception("get_clear_task_progress error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/document/clear/data — 查询切片清洗数据
# 对应 jusure_AI DocClearDataView GET /ai/document/clear/data
# ---------------------------------------------------------------------------

@router.get("/document/clear/data")
async def get_clear_data(
    task_id: str = Query(..., description="清洗任务 ID"), ):
    """
    查询清洗后的切片内容列表。
    对应 jusure_AI DocClearDataView GET /ai/document/clear/data
    """
    try:
        tenant_id = current_tenant()
        result = await svc.get_clear_data(task_id=task_id)
        return api_success(data={"data_list": result, "total": len(result)})
    except Exception as e:
        logger.exception("get_clear_data error")
        raise HTTPException(status_code=500, detail=str(e))

# -*- coding: utf-8 -*-
"""
知识库服务 API 路由
对外接口与 jusure_AI 保持一致，内部通过映射对齐 RAGflow 架构
"""
import re
from typing import Any
from fastapi import APIRouter
from fastapi import Query
from fastapi import Header
from fastapi import HTTPException
from fastapi import Depends
from fastapi import Body

from common.auth_context import (
    RequestContext,
    get_current_request_context,
    get_request_context,
    pick_user,
)
from common.models import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, DocumentCreate, DocumentImportItem, TemplateDocumentImportItem, get_db
)
from common.utils import (
    NotFoundException, ValidationException, get_logger
)
from common.utils.response import api_error, api_success
from common.storage import get_message_queue
from .core_services import (
    KnowledgeBaseService, DocumentService, TaskService, KnowledgeExtService, KnowledgeGroupService, KnowledgeGroupKBService, ROLE_HIERARCHY, UserPermGroupService, KBPermGrantService, )
from .services.document_executor_service import DocumentExecutorService
# from .services.graph_service import GraphService  # 暂时注释，避免循环导入
from .services.document_clean_service import (
    DocumentCleanRuleService, DocumentRuleRelationService, KnowledgeRulePresetService, DocumentCleanTaskService, )

logger = get_logger("knowledge_api")
DEFAULT_TENANT_ID = "default"

router = APIRouter(prefix="/ai", tags=["Knowledge Base"], dependencies=[Depends(get_request_context)])

def normalize_tenant_id(tenant_id: str | None, body: dict[str, Any] | None = None) -> str:
    """统一从请求上下文获取租户，忽略前端 query/body 中的 tenant_id。"""
    return str(get_current_request_context().tenant_id or DEFAULT_TENANT_ID)

def current_operator(default: str = "") -> str:
    """统一从 token/header 获取操作者，忽略前端传递的 user_id。"""
    return pick_user(get_current_request_context(), default=default)

def parse_date_to_timestamp(value: str | None) -> int | None:
    """将 YYYY-MM-DD/ISO 日期转换为毫秒时间戳。"""
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return None

# ============== 依赖注入 ==============

def get_kb_service(db=Depends(get_db)) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)

def get_doc_service(db=Depends(get_db)) -> DocumentService:
    return DocumentService(db)

def get_task_service(db=Depends(get_db)) -> TaskService:
    return TaskService(db)

def get_ext_service(db=Depends(get_db)) -> KnowledgeExtService:
    return KnowledgeExtService(db)

# ============== 知识库接口 /ai/knowledge ==============

@router.get("/knowledge")
async def list_knowledge_bases(
    tenant_id: str | None = Query(None, description="租户ID（对应 corpid）"), user_id: str | None = Query(None, description="用户ID，用于权限过滤"), page_no: int = Query(1, ge=1, description="页码"), page_num: int | None = Query(None, ge=1, description="前端兼容字段：页码"), page_size: int = Query(10, ge=1, le=100, description="每页数量"), knowledge_name: str | None = Query(None, description="知识库名称（模糊查询）"), knowledge_id: str | None = Query(None, description="知识库ID（精确查询单条）"), scope: int | None = Query(None, description="权限类型: 0=公共, 1=个人, 2=私有"), sort_field: str | None = Query(None, description="排序字段"), sort_order: str | None = Query("desc", description="排序方向: asc/desc"), group_id: str | None = Query(None, description="群组ID，用于按群组过滤知识库"), service: KnowledgeBaseService = Depends(get_kb_service)
):
    """获取知识库列表（与 jusure_AI GET /ai/knowledge 对齐）

    - 传入 knowledge_id：返回单条详情
    - 否则返回列表（支持 scope 过滤 + 权限过滤）
    """
    tenant_id = normalize_tenant_id(tenant_id)
    user_id = current_operator()
    if knowledge_id:
        # 精确查询单条
        kb = await service.get_by_id(knowledge_id, tenant_id)
        if not kb:
            return api_error("知识库不存在")
        data = kb.to_dict()
        data["role_status"] = True
        return api_success(data=data)

    # 前端 knowledge-web 使用 page_num，旧接口使用 page_no；这里统一转换，
    # 避免新同学在前后端字段名不一致时排查困难。
    current_page = page_num or page_no

    order_by = sort_field or "create_time"
    desc_order = (sort_order or "desc").lower() != "asc"

    kbs, total = await service.list(
        tenant_id=tenant_id, user_id=user_id, scope=scope, page=current_page, page_size=page_size, name=knowledge_name, order_by=order_by, desc=desc_order, group_id=group_id, )

    data = {
        "list": [kb.to_dict() for kb in kbs], "total": total, "page_no": current_page, "page_num": current_page, "page_size": page_size, "role_status": True, }
    return api_success(data=data)

@router.post("/knowledge")
async def create_or_update_knowledge_base(
    tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None, description="Header 中的用户 ID（优先级高于 user_id Query）"), body: dict[str, Any] = Body(...), service: KnowledgeBaseService = Depends(get_kb_service)
):
    """创建或更新知识库（与 jusure_AI POST /ai/knowledge 对齐）

    - 携带 knowledge_id 时：更新已有知识库
    - 否则：创建新知识库
    """
    try:
        tenant_id = normalize_tenant_id(tenant_id, body)
        logger.info(f"Creating knowledge base, tenant_id={tenant_id}, body={body}")
        operator = current_operator()

        # 提取 knowledge_id 判断是创建还是更新
        knowledge_id = body.get("knowledge_id")

        if knowledge_id:
            # 更新逻辑
            kb = await service.get_by_id(knowledge_id, tenant_id)
            if not kb:
                return api_error("知识库不存在，请刷新重试")

            update_data = KnowledgeBaseUpdate.model_validate({
                "knowledge_name": body.get("knowledge_name"), "knowledge_desc": body.get("knowledge_desc"), "scope": body.get("scope"), "graph_enable": body.get("graph_enable"), "parser_config": body.get("parser_config"), "group_id": body.get("group_id"), })
            kb = await service.update(knowledge_id, tenant_id, update_data)
            return api_success(data={"knowledge_id": kb.id})
        else:
            # 创建逻辑
            create_data = KnowledgeBaseCreate.model_validate({
                "knowledge_name": body["knowledge_name"], "knowledge_desc": body.get("knowledge_desc") or body.get("description", ""), "language": body.get("language", "Chinese"), "scope": body.get("scope", 0), "aigc_model_id": body.get("aigc_model_id") or body.get("embeddingModel"), "parser_id": body.get("parser_id", "naive"), "parser_config": body.get("parser_config", {}), "graph_enable": body.get("graph_enable", 0), "group_id": body.get("group_id"), })
            logger.info(f"Calling service.create with data: {create_data}")
            kb = await service.create(tenant_id=tenant_id, data=create_data, created_by=operator)
            logger.info(f"Knowledge base created: {kb.id}")
            return api_success(data={"knowledge_id": kb.id})
    except Exception as e:
        logger.exception(f"Error creating knowledge base: {e}")
        raise

@router.delete("/knowledge")
async def delete_knowledge_base(
    tenant_id: str | None = Query(None, description="租户ID"), user_id: str | None = Query(None, description="用户ID（用于创建人校验）"), x_user_id: str | None = Header(None, description="Header 中的用户ID（优先级高于 user_id Query）"), body: dict[str, Any] = Body(...), service: KnowledgeBaseService = Depends(get_kb_service)
):
    """删除知识库（与 jusure_AI DELETE /ai/knowledge 对齐）

    权限规则：传入 user_id 时只有创建人可删除，否则返回 403
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    if not knowledge_id:
        return api_error("knowledge_id 不能为空")

    operator = current_operator()

    kb = await service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在，请刷新重试")

    try:
        await service.delete(knowledge_id, tenant_id, user_id=operator)
    except ValidationException as e:
        raise HTTPException(status_code=403, detail=str(e))
    except NotFoundException:
        return api_error("知识库不存在，请刷新重试")

    return api_success(data={"knowledge_id": knowledge_id})

@router.put("/knowledge")
async def update_knowledge_base_status(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), service: KnowledgeBaseService = Depends(get_kb_service)
):
    """更新知识库状态（与 jusure_AI PUT /ai/knowledge 对齐）

    body: { knowledge_id, status: 0/1 }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    status = body.get("status")
    if not knowledge_id:
        return api_error("knowledge_id 不能为空")

    kb = await service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    update_data = KnowledgeBaseUpdate.model_validate({"status": status})
    await service.update(knowledge_id, tenant_id, update_data)
    return api_success(data={"knowledge_id": knowledge_id})

# ============== 文档接口 /ai/knowledge/doc ==============

@router.get("/knowledge/doc")
async def list_or_get_documents(
    tenant_id: str | None = Query(None, description="租户ID"), knowledge_id: str | None = Query(None, description="知识库ID"), document_id: str | None = Query(None, description="文档ID（精确查询单条）"), page_no: int = Query(1, ge=1), page_num: int | None = Query(None, ge=1, description="前端兼容字段：页码"), page_size: int = Query(10, ge=1, le=100), doc_name: str | None = Query(None, description="文档名称（模糊查询）"), document_name: str | None = Query(None, description="前端兼容字段：文档名称"), state: str | None = Query(None, description="文档状态过滤"), status: str | None = Query(None, description="前端兼容字段：文档状态"), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service)
):
    """获取文档列表或单条详情。

    字段兼容：
    - 旧接口：page_no、doc_name、state
    - knowledge-web：page_num、document_name、status
    """
    tenant_id = normalize_tenant_id(tenant_id)
    if document_id:
        doc = await doc_service.get_by_id(document_id)
        if not doc:
            return api_error("文档不存在")
        return api_success(data=doc.to_dict())

    if not knowledge_id:
        return api_error("knowledge_id 不能为空")

    kb = await kb_service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    current_page = page_num or page_no
    current_doc_name = document_name or doc_name
    current_status = status or state

    docs, total = await doc_service.list_by_kb(
        kb_id=knowledge_id, page=current_page, page_size=page_size, name=current_doc_name, status=current_status, )

    return api_success(data={
        "list": [doc.to_dict() for doc in docs], "total": total, "page_no": current_page, "page_num": current_page, "page_size": page_size, })

@router.post("/knowledge/doc")
async def register_documents(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service), task_service: TaskService = Depends(get_task_service)
):
    """登记文档并触发解析（与 jusure_AI POST /ai/knowledge/doc 对齐）

    body 示例：
    {
        "knowledge_id": "xxx", "doc_list": [{"doc_name": "xx.pdf", "doc_type": "pdf", "doc_url": "oss://...", "doc_size": 1024}], "slice_model": 0, "chunk_size": 256, "chunk_overlap": 20, "pdf_model": 0
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    doc_list = body.get("doc_list", [])
    slice_model = body.get("slice_model", 0)
    chunk_size = body.get("chunk_size", 256)
    chunk_overlap = body.get("chunk_overlap", 20)
    pdf_model = body.get("pdf_model", 0)

    if not knowledge_id:
        return api_error("knowledge_id 不能为空")
    if not doc_list:
        return api_error("文档数量不能为0")

    kb = await kb_service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    # parser_config：将前端参数映射为解析器消费的字段名
    parser_config = {
        "chunk_token_num": chunk_size, "overlap_percent": chunk_overlap, "slice_model": slice_model, "pdf_model": pdf_model, }

    created_docs = []
    task_ids = []

    for doc_item in doc_list:
        doc_name = doc_item.get("doc_name", "")
        # jusure_AI 约定：doc_name 可能带前缀 "uuid_filename"，取后半部分
        if "_" in doc_name:
            try:
                doc_name = doc_name.split("_", 1)[-1]
            except Exception:
                pass

        doc = await doc_service.create(
            tenant_id=tenant_id, kb_id=knowledge_id, data=DocumentCreate.model_validate({
                "kb_id": knowledge_id, "name": doc_name, "type": doc_item.get("doc_type", ""), "size": doc_item.get("doc_size", 0), "location": doc_item.get("doc_url", ""), "parser_id": kb.parser_id, "parser_config": parser_config, "source_type": "local", })
        )

        task = await task_service.create(
            tenant_id=tenant_id, kb_id=knowledge_id, doc_id=doc.id, task_type="parse", )

        mq = get_message_queue()
        await mq.produce("jusure:task:parse", {
            "task_id": task.id, "doc_id": doc.id, "kb_id": knowledge_id, "tenant_id": tenant_id, })

        created_docs.append({**doc.to_dict(), "task_id": task.id})
        task_ids.append(task.id)

    await kb_service.increment_doc_count(knowledge_id, delta=len(created_docs))

    return api_success(data={
        "knowledge_id": knowledge_id, "doc_list": created_docs, "task_ids": task_ids, })

@router.delete("/knowledge/doc")
async def delete_document(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), doc_service: DocumentService = Depends(get_doc_service), task_service: TaskService = Depends(get_task_service)
):
    """删除文档（支持单个或批量）。

    兼容请求体：
    - 旧接口：{ "document_id": "xxx" }
    - knowledge-web：{ "doc_ids": "id1, id2" } 或 { "doc_ids": ["id1", "id2"] }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    raw_doc_ids = body.get("document_id") or body.get("doc_id") or body.get("doc_ids")
    if not raw_doc_ids:
        return api_error("document_id/doc_ids 不能为空")

    if isinstance(raw_doc_ids, str):
        document_ids = [doc_id.strip() for doc_id in raw_doc_ids.split(", ") if doc_id.strip()]
    elif isinstance(raw_doc_ids, list):
        document_ids = [str(doc_id).strip() for doc_id in raw_doc_ids if str(doc_id).strip()]
    else:
        document_ids = [str(raw_doc_ids).strip()]

    deleted_ids = []
    not_found_ids = []
    for document_id in document_ids:
        doc = await doc_service.get_by_id(document_id)
        if not doc:
            not_found_ids.append(document_id)
            continue
        await task_service.delete_by_doc(document_id)
        await doc_service.delete(document_id)
        deleted_ids.append(document_id)

    if not deleted_ids:
        return api_error("文档不存在")

    return api_success(data={
        "document_ids": deleted_ids, "not_found_ids": not_found_ids, })

# ============== 文档保存接口 /ai/knowledge/doc/save ==============

@router.post("/knowledge/doc/save")
async def save_documents(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service)
):
    """只存储文档信息，不触发解析（与 jusure_AI POST /ai/knowledge/doc/save 对齐）

    body 示例：
    {
        "knowledge_id": "xxx", "aigc_model_id": "yyy", "doc_list": [{"doc_name": "xx.pdf", "doc_type": "pdf", "doc_url": "oss://...", "doc_size": 1024}], "chunk_size": 256, "chunk_overlap": 20, "slice_model": 0, "pdf_model": 0
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    aigc_model_id = body.get("aigc_model_id", "")
    doc_list = body.get("doc_list", [])
    chunk_size = body.get("chunk_size", 256)
    chunk_overlap = body.get("chunk_overlap", 20)
    slice_model = body.get("slice_model", 0)
    pdf_model = body.get("pdf_model", 0)

    if not knowledge_id:
        return api_error("knowledge_id 不能为空")

    kb = await kb_service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    parser_config = {
        "chunk_token_num": chunk_size, "overlap_percent": chunk_overlap, "slice_model": slice_model, "pdf_model": pdf_model, }

    processed_docs = []
    for doc_item in doc_list:
        doc_name = doc_item.get("doc_name", "")
        if "_" in doc_name:
            try:
                doc_name = doc_name.split("_", 1)[-1]
            except Exception:
                pass

        try:
            doc = await doc_service.create(
                tenant_id=tenant_id, kb_id=knowledge_id, data=DocumentCreate.model_validate({
                    "kb_id": knowledge_id, "name": doc_name, "type": doc_item.get("doc_type", ""), "size": doc_item.get("doc_size", 0), "location": doc_item.get("doc_url", ""), "parser_id": kb.parser_id, "parser_config": parser_config, "source_type": "local", })
            )
            processed_docs.append({
                **doc_item, "document_id": doc.id, })
        except Exception as e:
            logger.error(f"Error saving document {doc_item.get('doc_name')}: {e}")
            continue

    await kb_service.increment_doc_count(knowledge_id, delta=len(processed_docs))

    return api_success(data={
        "knowledge_id": knowledge_id, "doc_list": processed_docs, "aigc_model_id": aigc_model_id, "pdf_model": pdf_model, })

# ============== 文档解析控制接口（兼容内部调用） ==============

@router.post("/knowledge/doc/run")
async def run_documents(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), doc_service: DocumentService = Depends(get_doc_service), task_service: TaskService = Depends(get_task_service)
):
    """启动文档解析任务"""
    tenant_id = normalize_tenant_id(tenant_id, body)
    doc_ids = body.get("document_ids") or body.get("doc_ids", [])
    if not doc_ids:
        return api_error("document_ids 不能为空")

    task_ids = []
    for document_id in doc_ids:
        doc = await doc_service.get_by_id(document_id)
        if not doc:
            continue
        await doc_service.run(document_id)
        task = await task_service.create(
            tenant_id=doc.tenant_id, kb_id=doc.kb_id, doc_id=document_id, task_type="parse", )
        mq = get_message_queue()
        await mq.produce("jusure:task:parse", {
            "task_id": task.id, "doc_id": document_id, "kb_id": doc.kb_id, "tenant_id": doc.tenant_id, })
        task_ids.append(task.id)

    return api_success(data={"task_ids": task_ids, "message": f"Started {len(task_ids)} documents"})

@router.post("/knowledge/doc/stop")
async def stop_documents(
    body: dict[str, Any] = Body(...), doc_service: DocumentService = Depends(get_doc_service)
):
    """停止文档解析任务"""
    doc_ids = body.get("document_ids") or body.get("doc_ids", [])
    for document_id in doc_ids:
        await doc_service.stop(document_id)
    return api_success(data={"message": f"Stopped {len(doc_ids)} documents"})

# ============== 高优先级新增接口 ==============

@router.get("/knowledge/all")
async def list_all_knowledge(
    tenant_id: str | None = Query(None, description="租户ID"), scope: int | None = Query(None, description="权限类型过滤: 0=公共, 1=个人"), knowledge_name: str | None = Query(None, description="知识库名称（模糊查询）"), page_no: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), group_id: str | None = Query(None, description="群组ID，用于按群组过滤知识库"), ext_service: KnowledgeExtService = Depends(get_ext_service), ):
    """全量知识库查询（不做权限过滤），对应 jusure_AI KnowledgeAllView GET /ai/knowledge/all"""
    tenant_id = normalize_tenant_id(tenant_id)
    kbs, total = await ext_service.list_all(
        tenant_id=tenant_id, scope=scope, name=knowledge_name, page=page_no, page_size=page_size, group_id=group_id, )
    return api_success(data={
        "list": [kb.to_dict() for kb in kbs], "total": total, "page_no": page_no, "page_size": page_size, })

@router.get("/knowledge/tree")
async def get_knowledge_tree(
    tenant_id: str | None = Query(None, description="租户ID"), scope: int | None = Query(None, description="权限类型过滤"), knowledge_name: str | None = Query(None, description="知识库名称（模糊查询）"), page_no: int = Query(1, ge=1), page_size: int = Query(1000, ge=1, le=5000), ext_service: KnowledgeExtService = Depends(get_ext_service), ):
    """知识库树形结构，对应 jusure_AI KnowledgeTreeView GET /ai/knowledge/tree"""
    tenant_id = normalize_tenant_id(tenant_id)
    data = await ext_service.get_tree(
        tenant_id=tenant_id, scope=scope, name=knowledge_name, page=page_no, page_size=page_size, )
    return api_success(data=data)

@router.get("/knowledge/doc/update")
async def list_docs_by_date(
    tenant_id: str | None = Query(None, description="租户ID"), knowledge_id: str = Query(..., description="知识库ID"), start_time: str | None = Query(None, description="起始时间 ISO 格式"), end_time: str | None = Query(None, description="结束时间 ISO 格式"), doc_name: str | None = Query(None, description="文档名称（模糊）"), state: str | None = Query(None, description="文档状态过滤"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), ext_service: KnowledgeExtService = Depends(get_ext_service), ):
    """按时间段/名称查询文档，对应 jusure_AI KnowledgeDocumentUpdate GET /ai/knowledge/doc/update"""
    docs, total = await ext_service.list_docs_by_date(
        knowledge_id=knowledge_id, start_time=start_time, end_time=end_time, doc_name=doc_name, state=state, page=page_no, page_size=page_size, )
    return api_success(data={
        "list": [d.to_dict() for d in docs], "total": total, "page_no": page_no, "page_size": page_size, })

@router.delete("/knowledge/doc/update")
async def batch_delete_docs_by_condition(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), ext_service: KnowledgeExtService = Depends(get_ext_service), ):
    """按条件批量删除文档，对应 jusure_AI KnowledgeDocumentUpdate DELETE /ai/knowledge/doc/update

    body: {
        knowledge_id, key_chose("doc_ids"|"time"), doc_ids: [...], # key_chose=doc_ids 时有效
        start_time, end_time      # key_chose=time 时有效
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    if not knowledge_id:
        return api_error("knowledge_id 不能为空")
    key_chose = body.get("key_chose", "doc_ids")
    doc_ids = body.get("doc_ids", [])
    start_time = body.get("start_time")
    end_time = body.get("end_time")

    deleted_count = await ext_service.batch_delete_docs(
        knowledge_id=knowledge_id, doc_ids=doc_ids, start_time=start_time, end_time=end_time, key_chose=key_chose, )
    return api_success(data={"deleted_count": deleted_count})

@router.post("/knowledge/doc/batch/continue/handle")
async def batch_continue_handle_docs(
    tenant_id: str | None = Query(None, description="租户ID"), body: dict[str, Any] = Body(...), ext_service: KnowledgeExtService = Depends(get_ext_service), ):
    """批量继续处理文档（重新发起解析任务），对应 jusure_AI KnowledgeDocBatchContinueHandleView POST

    body: {
        knowledge_id: str, doc_list: [{ document_id, parser_config(可选) }, ...]
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    doc_list = body.get("doc_list", [])
    if not knowledge_id:
        return api_error("knowledge_id 不能为空")
    if not doc_list:
        return api_error("doc_list 不能为空")

    result = await ext_service.batch_continue_handle(
        tenant_id=tenant_id, knowledge_id=knowledge_id, doc_list=doc_list, )
    return api_success(data=result)

# ============== 知识图谱 GraphRAG 接口 ==============

@router.post("/knowledge/graph/extract")
@router.get("/knowledge/graph")
@router.get("/knowledge/graph/{graph_id}")
@router.delete("/knowledge/graph/{graph_id}")
@router.post("/knowledge/graph/search")
@router.get("/statistic/knowledge")
async def get_knowledge_statistics(
    tenant_id: str | None = Query(None, description="租户 ID"), knowledge_id: str | None = Query(None, description="知识库 ID（可选，查询单个知识库统计）"), start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD"), end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service)
):
    """获取知识库统计数据
    
    返回：
    - total_knowledge: 知识库总数
    - total_documents: 文档总数
    - total_chunks: 切片总数
    - active_knowledge: 活跃知识库数
    - document_stats: 按类型统计的文档数
    - recent_uploads: 最近上传的文档数（近 7 天）
    """
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        # 基础统计
        all_kbs, _ = await kb_service.list(
            tenant_id=tenant_id, page=1, page_size=1, order_by="create_time", desc=False
        )
        
        # 获取所有知识库 ID
        all_kb_ids = [kb.id for kb in all_kbs]
        if knowledge_id:
            all_kb_ids = [knowledge_id]
        
        total_docs = 0
        total_chunks = 0
        doc_type_stats = {}
        
        for kb_id in all_kb_ids:
            docs, _ = await doc_service.list_by_kb(kb_id=kb_id, page=1, page_size=1)
            if docs:
                total_docs += len(docs)
                # 简单估算切片数（实际应该从 chunk 表查询）
                total_chunks += sum(doc.chunk_count for doc in docs)
                # 文档类型统计
                for doc in docs:
                    doc_type = doc.type or "unknown"
                    doc_type_stats[doc_type] = doc_type_stats.get(doc_type, 0) + 1
        
        # 活跃知识库（有文档的）
        active_count = len([kb_id for kb_id in all_kb_ids if True])  # 简化：假设有文档就算活跃
        
        # 最近上传（简化实现：查询所有文档的前 7 天）
        recent_uploads = 0  # TODO: 实际应该按 create_time 过滤
        
        data = {
            "total_knowledge": len(all_kb_ids) if not knowledge_id else 1, "total_documents": total_docs, "total_chunks": total_chunks, "active_knowledge": active_count, "document_stats": doc_type_stats, "recent_uploads": recent_uploads, }
        
        return api_success(data=data)
    except Exception as e:
        logger.exception("get_knowledge_statistics error")
        return api_error(f"获取统计数据异常：{str(e)}")

@router.get("/knowledge/doc/count")
async def get_document_count(
    tenant_id: str | None = Query(None, description="租户 ID"), knowledge_id: str | None = Query(None, description="知识库 ID 列表（逗号分隔）"), doc_type: str | None = Query(None, description="文档类型过滤"), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service)
):
    """获取文档/应用/视频数量统计
    
    返回：
    - document_count: 文档总数
    - pdf_count: PDF 文档数
    - docx_count: DOCX 文档数
    - excel_count: Excel 文档数
    - video_count: 视频数（预留）
    - audio_count: 音频数（预留）
    """
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        # 解析 knowledge_id 列表
        kb_ids = []
        if knowledge_id:
            kb_ids = [kid.strip() for kid in knowledge_id.split(", ") if kid.strip()]
        
        total_docs = 0
        type_counts = {}
        
        # 如果指定了 knowledge_id，只查询这些知识库
        target_kb_ids = kb_ids if kb_ids else []
        
        if not target_kb_ids:
            # 查询所有知识库
            all_kbs, _ = await kb_service.list(
                tenant_id=tenant_id, page=1, page_size=1000, order_by="create_time", desc=False
            )
            target_kb_ids = [kb.id for kb in all_kbs]
        
        # 统计每个知识库的文档
        for kb_id in target_kb_ids:
            page = 1
            while True:
                docs, total = await doc_service.list_by_kb(
                    kb_id=kb_id, page=page, page_size=100
                )
                if not docs:
                    break
                
                for doc in docs:
                    total_docs += 1
                    dtype = (doc.type or "unknown").lower()
                    type_counts[dtype] = type_counts.get(dtype, 0) + 1
                
                if len(docs) < 100:
                    break
                page += 1
        
        data = {
            "document_count": total_docs, "pdf_count": type_counts.get("pdf", 0), "docx_count": type_counts.get("docx", 0), "excel_count": type_counts.get("xlsx", 0) + type_counts.get("xls", 0), "ppt_count": type_counts.get("pptx", 0), "txt_count": type_counts.get("txt", 0), "md_count": type_counts.get("md", 0), "video_count": 0, # 预留：由 media-service 提供
            "audio_count": 0, # 预留：由 media-service 提供
            "other_count": sum(v for k, v in type_counts.items() if k not in ["pdf", "docx", "xlsx", "xls", "pptx", "txt", "md"])
        }
        
        return api_success(data=data)
    except Exception as e:
        logger.exception("get_document_count error")
        return api_error(f"获取文档统计异常：{str(e)}")

@router.get("/knowledge/doc/upload/history")
async def get_upload_history(
    tenant_id: str | None = Query(None, description="租户 ID"), knowledge_id: str | None = Query(None, description="知识库 ID"), user_id: str | None = Query(None, description="用户 ID"), start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD"), end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), doc_service: DocumentService = Depends(get_doc_service)
):
    """文档上传历史记录
    
    支持按时间范围、知识库、用户过滤
    """
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        user_id = current_operator()
        # 简单实现：查询文档列表（按创建时间排序）
        # TODO: 实际应该有专门的 upload_history 表
        filters = {}
        if knowledge_id:
            filters["kb_id"] = knowledge_id
        
        docs, total = await doc_service.list(
            page=page_no, page_size=page_size, tenant_id=tenant_id, **filters
        )
        
        # 如果有时间范围，在内存中过滤（简化实现）
        start_ts = parse_date_to_timestamp(start_date)
        end_ts = parse_date_to_timestamp(end_date)
        if start_ts is not None or end_ts is not None:
            filtered_docs = []
            for doc in docs:
                doc_date = doc.create_time
                if start_ts is not None and doc_date < start_ts:
                    continue
                if end_ts is not None and doc_date > end_ts:
                    continue
                filtered_docs.append(doc)
            docs = filtered_docs
            total = len(docs)
        
        history_list = []
        for doc in docs:
            history_list.append({
                "document_id": doc.id, "doc_name": doc.name, "doc_type": doc.type, "doc_size": doc.size, "upload_time": doc.create_time, "uploader": getattr(doc, "created_by", None) or "unknown", "knowledge_id": doc.kb_id, "status": doc.status, })
        
        return api_success(data={
            "list": history_list, "total": total, "page_no": page_no, "page_size": page_size, })
    except Exception as e:
        logger.exception("get_upload_history error")
        return api_error(f"获取上传历史异常：{str(e)}")

@router.get("/knowledge/model")
async def get_knowledge_models(
    tenant_id: str | None = Query(None, description="租户 ID"), knowledge_id: str | None = Query(None, description="知识库 ID"), model_type: str | None = Query(None, description="模型类型：embedding/chat"), ):
    """知识库关联模型查询
    
    返回该知识库使用的所有模型信息
    """
    try:
        # TODO: 实际应该查询 AIModelModel 表
        # 这里先返回空数据结构，由 model-service 提供实际数据
        models = []
        
        # 如果指定了 knowledge_id，查询该知识库的模型
        if knowledge_id:
            # TODO: 查询知识库绑定的模型
            pass
        else:
            # 查询所有模型
            # TODO: 调用 model-service 的接口
            pass
        
        return api_success(data={
            "list": models, "total": len(models), })
    except Exception as e:
        logger.exception("get_knowledge_models error")
        return api_error(f"获取模型列表异常：{str(e)}")

# ============== 文档清洗接口 ==============
# 对应 jusure_AI FileClearDataView, FileClearTableView, FileClearRelationView, KnowledgeClearRelationView

@router.get("/knowledge/clean/rule")
async def list_clean_rules(
    tenant_id: str | None = Query(None, description="租户 ID"), rule_type: int | None = Query(None, description="规则类型：0-脚本，1-模型"), doc_type: int | None = Query(None, description="适用文档类型：0-通用，1-文本，2-Excel, 3-QA"), is_builtin: bool | None = Query(None, description="是否内置：true/false"), page_no: int = Query(1, ge=1, description="页码"), page_size: int = Query(10, ge=1, le=100, description="每页数量"), db=Depends(get_db), ):
    """获取文档清洗规则列表"""
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        service = DocumentCleanRuleService(db)
        result = await service.list_rules(
            tenant_id=tenant_id, rule_type=rule_type, doc_type=doc_type, is_builtin=is_builtin, page=page_no, page_size=page_size, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("list_clean_rules error")
        return api_error(f"获取规则列表异常：{str(e)}")

@router.post("/knowledge/clean/rule")
async def create_clean_rule(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """创建文档清洗规则
    
    body: {
        rule_name: str, # 规则名称
        rule_content: str, # 规则内容（提示词/脚本）
        rule_desc: str | None, # 规则描述
        rule_type: int = 0, # 规则类型：0-脚本，1-模型
        doc_type: int = 0, # 适用文档类型
        is_builtin: int = 0      # 是否内置
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = DocumentCleanRuleService(db)
        
        if not body.get("rule_name"):
            return api_error("规则名称不能为空")
        if not body.get("rule_content"):
            return api_error("规则内容不能为空")
        
        rule_data = {
            "tenant_id": tenant_id, "rule_name": body.get("rule_name"), "rule_content": body.get("rule_content"), "rule_desc": body.get("rule_desc", ""), "rule_type": body.get("rule_type", 0), "doc_type": body.get("doc_type", 0), "is_builtin": body.get("is_builtin", 0), }
        
        rule_id = await service.create_rule(rule_data)
        
        return api_success(data={"rule_id": rule_id}, message="创建成功")
    except Exception as e:
        logger.exception("create_clean_rule error")
        return api_error(f"创建规则异常：{str(e)}")

@router.put("/knowledge/clean/rule")
async def update_clean_rule(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """更新文档清洗规则
    
    body: {
        rule_id: str, # 规则 ID
        rule_name: str, # 规则名称
        rule_content: str, # 规则内容
        doc_type: int = 0        # 适用文档类型
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = DocumentCleanRuleService(db)
        
        rule_id = body.get("rule_id")
        if not rule_id:
            return api_error("rule_id 不能为空")
        
        update_data = {
            "rule_name": body.get("rule_name"), "rule_content": body.get("rule_content"), "doc_type": body.get("doc_type", 0), }
        
        success = await service.update_rule(rule_id, tenant_id, update_data)
        if not success:
            return api_error("规则不存在或更新失败")
        
        return api_success(data={"rule_id": rule_id}, message="更新成功")
    except Exception as e:
        logger.exception("update_clean_rule error")
        return api_error(f"更新规则异常：{str(e)}")

@router.delete("/knowledge/clean/rule")
async def delete_clean_rule(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """删除文档清洗规则
    
    body: {
        rule_id: str  # 规则 ID
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = DocumentCleanRuleService(db)
        rule_id = body.get("rule_id")
        
        if not rule_id:
            return api_error("rule_id 不能为空")
        
        success = await service.delete_rule(rule_id, tenant_id)
        if not success:
            return api_error("规则不存在或删除失败")
        
        return api_success(data={"rule_id": rule_id}, message="删除成功")
    except Exception as e:
        logger.exception("delete_clean_rule error")
        return api_error(f"删除规则异常：{str(e)}")

@router.get("/knowledge/clean/document/rules")
async def get_document_rules(
    tenant_id: str | None = Query(None, description="租户 ID"), document_id: str = Query(..., description="文档 ID"), db=Depends(get_db), ):
    """获取文档关联的清洗规则"""
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        service = DocumentRuleRelationService(db)
        rules = await service.get_document_rules(document_id, tenant_id)
        return api_success(data={"list": rules, "total": len(rules)})
    except Exception as e:
        logger.exception("get_document_rules error")
        return api_error(f"获取文档规则异常：{str(e)}")

@router.post("/knowledge/clean/document/rules")
async def add_document_rule(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """添加文档清洗规则关联
    
    body: {
        document_id: str, # 文档 ID
        rule_id: str, # 规则 ID
        rule_type: int = 0, priority: int = 0, enabled: int = 1
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = DocumentRuleRelationService(db)
        
        if not body.get("document_id"):
            return api_error("document_id 不能为空")
        if not body.get("rule_id"):
            return api_error("rule_id 不能为空")
        
        relation_data = {
            "tenant_id": tenant_id, "document_id": body.get("document_id"), "rule_id": body.get("rule_id"), "rule_type": body.get("rule_type", 0), "priority": body.get("priority", 0), "enabled": body.get("enabled", 1), }
        
        relation_id = await service.add_relation(relation_data)
        
        return api_success(data={"relation_id": relation_id}, message="添加成功")
    except Exception as e:
        logger.exception("add_document_rule error")
        return api_error(f"添加规则关联异常：{str(e)}")

@router.delete("/knowledge/clean/document/rules")
async def remove_document_rule(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """移除文档清洗规则关联
    
    body: {
        document_id: str, # 文档 ID
        rule_id: str       # 规则 ID
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = DocumentRuleRelationService(db)
        document_id = body.get("document_id")
        rule_id = body.get("rule_id")
        
        if not document_id or not rule_id:
            return api_error("document_id 和 rule_id 不能为空")
        
        success = await service.remove_relation(document_id, rule_id, tenant_id)
        if not success:
            return api_error("关联不存在或移除失败")
        
        return api_success(message="移除成功")
    except Exception as e:
        logger.exception("remove_document_rule error")
        return api_error(f"移除规则关联异常：{str(e)}")

@router.get("/knowledge/clean/preset")
async def get_knowledge_presets(
    tenant_id: str | None = Query(None, description="租户 ID"), knowledge_id: str = Query(..., description="知识库 ID"), db=Depends(get_db), ):
    """获取知识库预配置的清洗规则"""
    try:
        tenant_id = normalize_tenant_id(tenant_id)
        service = KnowledgeRulePresetService(db)
        presets = await service.get_knowledge_presets(knowledge_id, tenant_id)
        return api_success(data={"list": presets, "total": len(presets)})
    except Exception as e:
        logger.exception("get_knowledge_presets error")
        return api_error(f"获取预配置规则异常：{str(e)}")

@router.post("/knowledge/clean/preset")
async def add_knowledge_preset(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """添加知识库预配置规则
    
    body: {
        knowledge_id: str, # 知识库 ID
        rule_ids: list[str]  # 规则 ID 列表
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = KnowledgeRulePresetService(db)
        knowledge_id = body.get("knowledge_id")
        rule_ids = body.get("rule_ids", [])
        
        if not knowledge_id:
            return api_error("knowledge_id 不能为空")
        if not rule_ids:
            return api_error("rule_ids 不能为空")
        
        preset_ids = await service.add_preset(knowledge_id, rule_ids, tenant_id)
        
        return api_success(data={"preset_ids": preset_ids}, message="添加成功")
    except Exception as e:
        logger.exception("add_knowledge_preset error")
        return api_error(f"添加预配置规则异常：{str(e)}")

@router.put("/knowledge/clean/preset")
async def update_knowledge_preset(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """更新知识库预配置规则（先删后增）
    
    body: {
        knowledge_id: str, # 知识库 ID
        new_rule_ids: list[str], # 新规则 ID 列表
        old_rule_ids: list[str]  # 旧规则 ID 列表（要删除的）
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        service = KnowledgeRulePresetService(db)
        knowledge_id = body.get("knowledge_id")
        new_rule_ids = body.get("new_rule_ids", [])
        old_rule_ids = body.get("old_rule_ids", [])
        
        if not knowledge_id:
            return api_error("knowledge_id 不能为空")
        
        # 先删除旧的，再添加新的
        await service.update_presets(knowledge_id, new_rule_ids, old_rule_ids, tenant_id)
        
        return api_success(message="更新成功")
    except Exception as e:
        logger.exception("update_knowledge_preset error")
        return api_error(f"更新预配置规则异常：{str(e)}")

@router.post("/knowledge/clean/execute")
async def execute_document_clean(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """执行文档清洗
    
    body: {
        knowledge_id: str, # 知识库 ID
        document_id: str, # 文档 ID
        doc_url: str, # 文档 URL
        aigc_model_id: str | None, # AI 模型 ID（用于模型处理）
        use_knowledge_preset: bool = True  # 是否使用知识库预配置规则
    }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        clean_task_service = DocumentCleanTaskService(db)
        rule_relation_service = DocumentRuleRelationService(db)
        preset_service = KnowledgeRulePresetService(db)
        
        knowledge_id = body.get("knowledge_id")
        document_id = body.get("document_id")
        doc_url = body.get("doc_url")
        aigc_model_id = body.get("aigc_model_id")
        use_preset = body.get("use_knowledge_preset", True)
        
        if not knowledge_id or not document_id or not doc_url:
            return api_error("knowledge_id、document_id 和 doc_url 不能为空")
        
        # 创建清洗任务
        task_data = {
            "tenant_id": tenant_id, "knowledge_id": knowledge_id, "document_id": document_id, "task_type": "clean", "original_url": doc_url, "aigc_model_id": aigc_model_id, }
        task_id = await clean_task_service.create_task(task_data)
        
        # 获取应用的规则
        rules_to_apply = []
        
        # 1. 获取文档关联的规则
        doc_rules = await rule_relation_service.get_document_rules(document_id, tenant_id)
        rules_to_apply.extend(doc_rules)
        
        # 2. 如果使用预配置，获取知识库预配置规则
        if use_preset:
            preset_rules = await preset_service.get_knowledge_presets(knowledge_id, tenant_id)
            rules_to_apply.extend(preset_rules)
        
        # 去重（按 rule_id）
        seen_rule_ids = set()
        unique_rules = []
        for rule in rules_to_apply:
            if rule["rule_id"] not in seen_rule_ids:
                unique_rules.append(rule)
                seen_rule_ids.add(rule["rule_id"])
        
        # 更新任务状态为运行中
        await clean_task_service.update_task_state(task_id, "running", progress=0)
        
        # TODO: 实际应该异步执行清洗任务
        # 这里先返回任务信息
        return api_success(data={
            "task_id": task_id, "state": "pending", "message": "清洗任务已创建，正在排队处理", })
    except Exception as e:
        logger.exception("execute_document_clean error")
        return api_error(f"执行清洗异常：{str(e)}")

@router.get("/knowledge/clean/task")
async def get_clean_task(
    tenant_id: str | None = Query(None, description="租户 ID"), task_id: str = Query(..., description="任务 ID"), db=Depends(get_db), ):
    """获取清洗任务详情和进度"""
    try:
        service = DocumentCleanTaskService(db)
        task = await service.get_task(task_id, tenant_id)
        
        if not task:
            return api_error("任务不存在")
        
        return api_success(data=task.to_dict())
    except Exception as e:
        logger.exception("get_clean_task error")
        return api_error(f"获取任务详情异常：{str(e)}")

@router.post("/knowledge/clean/detect-language")
async def detect_document_language(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """智能检测文档语言
    
    body: {
        content: str, # 文档内容（采样前 1000 字符）
    }
    
    Returns:
        language: 'zh' (中文), 'en' (英文), 'mixed' (混合), 'unknown' (未知)
        confidence: float, # 置信度 (0-1)
        statistics: {              # 统计信息
            chinese_chars: int, # 中文字符数
            english_chars: int, # 英文字母数
            total_chars: int       # 总字符数
        }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        content = body.get("content", "")
        
        if not content:
            return api_error("content 不能为空")
        
        # 创建临时服务实例进行检测
        clean_service = DocumentCleanTaskService(db)
        
        # 调用检测方法
        language = clean_service._detect_language(content)
        
        # 计算统计信息
        sample = content[:1000]
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', sample))
        english_chars = len(re.findall(r'[a-zA-Z]', sample))
        total_chars = len(sample)
        
        # 计算置信度
        if total_chars > 0:
            chinese_ratio = chinese_chars / total_chars
            english_ratio = english_chars / total_chars
            
            if language == 'zh':
                confidence = chinese_ratio
            elif language == 'en':
                confidence = english_ratio
            elif language == 'mixed':
                confidence = min(chinese_ratio, english_ratio) * 2
            else:
                confidence = 0.0
        else:
            confidence = 0.0
        
        return api_success(data={
            "language": language, "confidence": round(confidence, 4), "statistics": {
                "chinese_chars": chinese_chars, "english_chars": english_chars, "total_chars": total_chars, }
        })
    except Exception as e:
        logger.exception("detect_document_language error")
        return api_error(f"语言检测异常：{str(e)}")

@router.post("/knowledge/doc/execute")
async def execute_document_process(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), db=Depends(get_db), ):
    """执行文档处理流程（读取 → 清洗 (可选) → 解析 → 分块）
    
    body: {
        knowledge_id: str, # 知识库 ID
        document_id: str, # 文档 ID
        content: str, # 文档内容（或从 OSS 读取）
        enable_cleaning: bool = True, # 是否启用清洗（默认开启）
        clean_rules: list | None, # 清洗规则列表（可选）
        parser_config: {             # 解析配置
            chunk_size: int = 256, chunk_overlap: int = 20, slice_model: int = 0, pdf_model: int = 0, }
    }
    
    Returns:
        {
            chunks: [...], # 分块结果
            cleaned: True/False, # 是否经过清洗
            clean_task_id: "...", # 清洗任务 ID（如果启用了清洗）
            total_chunks: 10, # 总切片数
            total_tokens: 5000, # 总 token 数
        }
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        knowledge_id = body.get("knowledge_id")
        document_id = body.get("document_id")
        content = body.get("content")
        enable_cleaning = body.get("enable_cleaning", True)
        clean_rules = body.get("clean_rules")
        parser_config = body.get("parser_config", {})
        
        if not knowledge_id or not document_id:
            return api_error("knowledge_id 和 document_id 不能为空")
        
        if not content:
            # TODO: 从 OSS 读取内容
            return api_error("content 不能为空，或提供 doc_url 从 OSS 读取")
        
        # 创建执行服务实例
        executor_service = DocumentExecutorService(db)
        
        # 执行文档处理流程
        result = await executor_service.execute(
            tenant_id=tenant_id, doc_id=document_id, kb_id=knowledge_id, content=content, enable_cleaning=enable_cleaning, clean_rules=clean_rules, parser_config=parser_config, )
        
        return api_success(data=result)
        
    except Exception as e:
        logger.exception("execute_document_process error")
        return api_error(f"执行文档处理异常：{str(e)}")

# ============== 群组依赖注入 ==============

def get_group_service(db=Depends(get_db)) -> KnowledgeGroupService:
    return KnowledgeGroupService(db)

def get_group_kb_service(db=Depends(get_db)) -> KnowledgeGroupKBService:
    return KnowledgeGroupKBService(db)

def extract_tenant_and_group_id(
    tenant_id_query: str | None, body: dict[str, Any] | None, group_id_path: str | None = None, ) -> tuple[str, str]:
    """从 Query 和 Body 中提取 tenant_id 和 group_id
    
    优先级：
    - tenant_id: Query 参数 > Body 字段 > None
    - group_id: 路径参数 > Body 字段
    
    Returns:
        (effective_tenant_id, effective_group_id)
    """
    effective_tenant_id = normalize_tenant_id(tenant_id_query, body)
    
    effective_group_id = group_id_path
    if (not effective_group_id or not effective_group_id.strip()) and body:
        effective_group_id = body.get("group_id", "")
    
    return effective_tenant_id, effective_group_id or ""

# ============== 知识库群组接口 /ai/knowledge/group ==============

@router.post("/knowledge/group")
async def create_knowledge_group(
    tenant_id: str | None = Query(None, description="租户 ID（Query 参数）"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None, description="Header 中的用户 ID（优先级高于 user_id Query）"), body: dict[str, Any] = Body(...), service: KnowledgeGroupService = Depends(get_group_service), ):
    """创建群组（根群组或子群组）

    body 示例：
    {{
        "name": "技术部", "description": "描述", "parent_id": null, // 为 null 创建根群组，传入 group_id 创建子群组
        "tenant_id": "1"      // 可选：也可以从 body 中获取 tenant_id
    }}
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    name = body.get("name", "").strip()
    if not name:
        return api_error("name 不能为空")

    # 规范化 parent_id：空字符串转为 None，确保根群组查询正确
    parent_id = body.get("parent_id")
    if parent_id == "":
        parent_id = None

    # 支持从 Query 或 Body 中获取 tenant_id，Query 优先级更高
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"

    operator = current_operator()
    try:
        group = await service.create(
            tenant_id=effective_tenant_id, name=name, description=body.get("description"), parent_id=parent_id, created_by=operator, )
        return api_success(data=group.to_dict())
    except NotFoundException as e:
        return api_error(str(e))

@router.get("/knowledge/group/tree")
async def get_knowledge_group_tree(
    tenant_id: str | None = Query(None, description="租户 ID"), root_id: str | None = Query(None, description="起始群组 ID，为空则返回全部根群组"), include_kbs: bool = Query(True, description="是否在每个群组节点上附加知识库列表"), service: KnowledgeGroupService = Depends(get_group_service), ):
    """获取群组完整树形结构（嵌套 children）"""
    tree = await service.get_tree(
        tenant_id=tenant_id, root_id=root_id, include_kbs=include_kbs, )
    return api_success(data={"list": tree, "total": len(tree)})

@router.get("/knowledge/group")
async def list_knowledge_groups(
    tenant_id: str | None = Query(None, description="租户 ID"), name: str | None = Query(None, description="群组名称（模糊查询，为空时返回所有群组）"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), service: KnowledgeGroupService = Depends(get_group_service), ):
    """列出群组
    
    - name 为空：返回该租户的所有群组（包括根群组和子群组）
    - name 有值：根据名称模糊搜索该租户的所有群组
    - 每个群组返回时附带 kb_count 字段表示该群组下的知识库数量
    """
    # name 为空时查询所有群组，有值时也查询所有群组进行过滤
    groups, total = await service.list_all(
        tenant_id=tenant_id, name=name if name and name.strip() else None, page=page_no, page_size=page_size, )
    return api_success(data={
        "list": groups, # list_all 已经返回字典列表，包含 kb_count
        "total": total, "page_no": page_no, "page_size": page_size, })

@router.get("/knowledge/group/{group_id}")
async def get_knowledge_group(
    group_id: str | None = None, tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """获取群组详情
    
    group_id 优先级：路径参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id, effective_group_id = extract_tenant_and_group_id(
        tenant_id, body, group_id
    )
    
    if not effective_group_id:
        return api_error("group_id 不能为空")
    
    # 转换为字符串
    if effective_tenant_id:
        effective_tenant_id = str(effective_tenant_id)
    
    try:
        group = await service.get_by_id_with_validation(effective_group_id, effective_tenant_id)
        return api_success(data=group.to_dict())
    except NotFoundException:
        return api_error("群组不存在")
    except ValidationException as e:
        return api_error(str(e))

@router.put("/knowledge/group")
async def update_knowledge_group(
    tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), service: KnowledgeGroupService = Depends(get_group_service), ):
    """更新群组名称/描述（需要 admin 或以上权限）
    
    body 示例：
    {{
        "group_id": "kg_xxx", // 必填：群组 ID
        "name": "新名称", // 可选：新名称
        "description": "新描述"   // 可选：新描述
    }}
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    # 从 Body 中获取 group_id
    group_id = body.get("group_id", "").strip()
    if not group_id:
        return api_error("group_id 不能为空")

    # 支持从 Query 或 Body 中获取 tenant_id，Query 优先级更高
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"

    operator = current_operator()
    if operator:
        has_perm = await service.check_permission(group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")
    try:
        group = await service.update(
            group_id=group_id, tenant_id=effective_tenant_id, name=body.get("name"), description=body.get("description"), )
        return api_success(data=group.to_dict())
    except NotFoundException as e:
        return api_error(str(e))

@router.delete("/knowledge/group")
async def delete_knowledge_group(
    group_id: str | None = Query(None, description="群组 ID"), tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID，需要 owner 权限"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """删除群组（返回前校验：无子群组且无知识库）
    
    group_id 优先级：Query 参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    
    方式 1：通过查询参数
    DELETE /ai/knowledge/group?group_id=kg_xxx&tenant_id=default
    
    方式 2：通过请求体
    {
        "group_id": "kg_xxx", "tenant_id": "default"
    }
    """
    effective_group_id = group_id
    if not effective_group_id and body:
        effective_group_id = body.get("group_id", "").strip()
    
    if not effective_group_id:
        return api_error("group_id 不能为空")
    
    effective_tenant_id = tenant_id
    if not effective_tenant_id or effective_tenant_id == "default":
        effective_tenant_id = body.get("tenant_id", "default") if body else "default"
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    # 转换为字符串
    effective_tenant_id = str(effective_tenant_id)
    
    operator = current_operator()
    try:
        await service.delete(effective_group_id, effective_tenant_id, user_id=operator)
        return api_success(data={"group_id": effective_group_id})
    except NotFoundException:
        return api_error("群组不存在")
    except ValidationException as e:
        return api_error(str(e))

@router.delete("/knowledge/group/{group_id}")
async def delete_knowledge_group_by_path(
    group_id: str | None = None, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID，需要 owner 权限"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """删除群组（返回前校验：无子群组且无知识库）
    
    group_id 优先级：路径参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id, effective_group_id = extract_tenant_and_group_id(
        tenant_id, body, group_id
    )
    
    if not effective_group_id:
        return api_error("group_id 不能为空")
    
    operator = current_operator()
    try:
        await service.delete(effective_group_id, effective_tenant_id, user_id=operator)
        return api_success(data={"group_id": effective_group_id})
    except NotFoundException:
        return api_error("群组不存在")
    except ValidationException as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/knowledge/group/{group_id}/children")
async def list_group_children(
    group_id: str | None = None, tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """列出直接子群组
    
    group_id 优先级：路径参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id, effective_group_id = extract_tenant_and_group_id(
        tenant_id, body, group_id
    )
    if not effective_group_id:
        return api_error("group_id 不能为空")
    children = await service.list_children(effective_group_id, effective_tenant_id)
    return api_success(data={
        "list": [c.to_dict() for c in children], "total": len(children), })

# ============== 群组成员管理 ==============

@router.get("/knowledge/group/{group_id}/members")
async def list_group_members(
    group_id: str | None = None, tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """列出群组成员
    
    group_id 优先级：路径参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id, effective_group_id = extract_tenant_and_group_id(
        tenant_id, body, group_id
    )
    if not effective_group_id:
        return api_error("group_id 不能为空")
    group = await service.get_by_id(effective_group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")
    members = await service.list_members(effective_group_id)
    return api_success(data={
        "list": [m.to_dict() for m in members], "total": len(members), })

@router.post("/knowledge/group/{group_id}/members")
async def add_group_member(
    group_id: str | None = None, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="操作者 ID（权限校验）"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), service: KnowledgeGroupService = Depends(get_group_service), ):
    """添加群组成员（需要 admin 或以上权限）

    body: {{ "user_id": "目标用户 ID", "role": "member", "group_id": "kg_xxx", "tenant_id": "1" }}
    
    group_id 优先级：路径参数 > Body 字段
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id, effective_group_id = extract_tenant_and_group_id(
        tenant_id, body, group_id
    )
    if not effective_group_id:
        return api_error("group_id 不能为空")
    
    operator = current_operator()
    if operator:
        has_perm = await service.check_permission(effective_group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")

    target_user_id = body.get("user_id", "").strip()
    role = body.get("role", "member")
    if not target_user_id:
        return api_error("user_id 不能为空")
    if role not in ROLE_HIERARCHY:
        return api_error(f"invalid role: {role}")

    group = await service.get_by_id(effective_group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    try:
        member = await service.add_member(effective_group_id, effective_tenant_id, target_user_id, role)
        return api_success(data=member.to_dict())
    except ValidationException as e:
        return api_error(str(e))

@router.put("/knowledge/group/{group_id}/members/{target_user_id}")
async def update_group_member_role(
    group_id: str, target_user_id: str, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="操作者 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), service: KnowledgeGroupService = Depends(get_group_service), ):
    """修改成员角色（需要 admin 或以上权限）
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    operator = current_operator()
    if operator:
        has_perm = await service.check_permission(group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")

    role = body.get("role", "member")
    if role not in ROLE_HIERARCHY:
        return api_error(f"invalid role: {role}")

    group = await service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    try:
        member = await service.add_member(group_id, effective_tenant_id, target_user_id, role)
        return api_success(data=member.to_dict())
    except ValidationException as e:
        return api_error(str(e))

@router.delete("/knowledge/group/{group_id}/members/{target_user_id}")
async def remove_group_member(
    group_id: str, target_user_id: str, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="操作者 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(None), service: KnowledgeGroupService = Depends(get_group_service), ):
    """移除群组成员（需要 admin 或以上权限）
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    operator = current_operator()
    if operator:
        has_perm = await service.check_permission(group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")

    group = await service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    removed = await service.remove_member(group_id, target_user_id)
    if not removed:
        return api_error("该成员不存在")
    return api_success(data={"group_id": group_id, "user_id": target_user_id})

# ============== 群组内知识库管理 ==============

@router.get("/knowledge/group/{group_id}/knowledge")
async def list_group_knowledge_bases(
    group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), knowledge_name: str | None = Query(None, description="知识库名称（模糊查询）"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), body: dict[str, Any] = Body(None), group_service: KnowledgeGroupService = Depends(get_group_service), kb_service: KnowledgeGroupKBService = Depends(get_group_kb_service), ):
    """列出群组内知识库
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    group = await group_service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")
    kbs, total = await kb_service.list_kbs_in_group(
        group_id=group_id, tenant_id=effective_tenant_id, page=page_no, page_size=page_size, name=knowledge_name, )
    return api_success(data={
        "list": [kb.to_dict() for kb in kbs], "total": total, "page_no": page_no, "page_size": page_size, })

@router.post("/knowledge/group/{group_id}/knowledge")
async def create_knowledge_base_in_group(
    group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), group_service: KnowledgeGroupService = Depends(get_group_service), kb_svc: KnowledgeBaseService = Depends(get_kb_service), ):
    """在群组下新建知识库（需要 member 或以上权限）

    body 示例：
    {{
        "knowledge_name": "项目文档", "knowledge_desc": "描述", "scope": 0, "language": "Chinese", "tenant_id": "1"      // 可选：也可以从 body 中获取 tenant_id
    }}
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    operator = current_operator()
    if operator:
        has_perm = await group_service.check_permission(group_id, operator, "member")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 member 或以上权限")

    group = await group_service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    knowledge_name = body.get("knowledge_name", "").strip()
    if not knowledge_name:
        return api_error("knowledge_name 不能为空")

    create_data = KnowledgeBaseCreate.model_validate({
        "knowledge_name": knowledge_name, "knowledge_desc": body.get("knowledge_desc", ""), "language": body.get("language", "Chinese"), "scope": body.get("scope", 0), "aigc_model_id": body.get("aigc_model_id"), "parser_id": body.get("parser_id", "naive"), "parser_config": body.get("parser_config", {}), "graph_enable": body.get("graph_enable", 0), })
    kb = await kb_svc.create(tenant_id=effective_tenant_id, data=create_data, created_by=operator)

    # 设置群组关联
    kb.group_id = group_id
    await kb_svc.session.flush()

    return api_success(data={**kb.to_dict(), "group_id": group_id})

@router.put("/knowledge/group/{group_id}/knowledge/{kb_id}")
async def attach_knowledge_base_to_group(
    group_id: str, kb_id: str, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(None), group_service: KnowledgeGroupService = Depends(get_group_service), kb_service: KnowledgeGroupKBService = Depends(get_group_kb_service), ):
    """将已有知识库关联到指定群组（需要 admin 或以上权限）
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    operator = current_operator()
    if operator:
        has_perm = await group_service.check_permission(group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")

    group = await group_service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    try:
        kb = await kb_service.attach_kb(kb_id, group_id, effective_tenant_id)
        return api_success(data=kb.to_dict())
    except NotFoundException:
        return api_error("知识库不存在")

@router.delete("/knowledge/group/{group_id}/knowledge/{kb_id}")
async def detach_knowledge_base_from_group(
    group_id: str, kb_id: str, tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(None), group_service: KnowledgeGroupService = Depends(get_group_service), kb_service: KnowledgeGroupKBService = Depends(get_group_kb_service), ):
    """将知识库从群组移除（group_id 设为 NULL，知识库本身不删除）
    
    tenant_id 优先级：Query 参数 > Body 字段 > 默认值 "default"
    """
    effective_tenant_id = normalize_tenant_id(tenant_id, body)
    if not effective_tenant_id or effective_tenant_id == "":
        effective_tenant_id = "default"
    
    operator = current_operator()
    if operator:
        has_perm = await group_service.check_permission(group_id, operator, "admin")
        if not has_perm:
            raise HTTPException(status_code=403, detail="需要 admin 或以上权限")

    group = await group_service.get_by_id(group_id, effective_tenant_id)
    if not group:
        return api_error("群组不存在")

    try:
        kb = await kb_service.detach_kb(kb_id, effective_tenant_id)
        return api_success(data=kb.to_dict())
    except NotFoundException:
        return api_error("知识库不存在")

@router.post("/knowledge/doc/import")
async def import_documents(
    tenant_id: str | None = Query(None, description="租户ID"), user_id: str | None = Query(None, description="用户ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service), task_service: TaskService = Depends(get_task_service), ):
    """精细化文档导入（按文件类型分类配置解析参数）

    body 示例：
    {{
        "knowledge_id": "kb_xxx", "documents": [
            {{
                "doc_category": "text", "name": "年度报告.pdf", "location": "minio://bucket/reports/2024.pdf", "size": 2048000, "tags": ["财务", "2024"], "parse_options": {{
                    "layout_analysis": true, "image_ocr": true, "multimodal_understanding": false, "chart_recognition": true, "formula_recognition": true, "knowledge_enhancement": true, "knowledge_graph_extraction": false, "chunk_strategy": "custom", "chunk_size": 512, "chunk_regex": "\\\\n\\\\n", "associate_filename": true
                }}
            }}, {{
                "doc_category": "web", "name": "产品文档页面", "source_url": "https://docs.example.com/product", "tags": ["官网"], "parse_options": {{
                    "urls": ["https://docs.example.com/product"], "css_selector": "article.main-content", "extract_links": true
                }}
            }}
        ]
    }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    documents = body.get("documents", [])

    if not knowledge_id:
        return api_error("knowledge_id 不能为空")
    if not documents:
        return api_error("documents 不能为空")

    kb = await kb_service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    operator = current_operator()
    created_docs = []
    task_ids = []

    try:
        for item_dict in documents:
            item = DocumentImportItem.model_validate(item_dict)
            doc = await doc_service.create_imported_document(
                tenant_id=tenant_id, kb_id=knowledge_id, item=item, parser_id=kb.parser_id, created_by=operator, )

            task = await task_service.create(
                tenant_id=tenant_id, kb_id=knowledge_id, doc_id=doc.id, task_type="parse", )

            mq = get_message_queue()
            await mq.produce("jusure:task:parse", {
                "task_id": task.id, "doc_id": doc.id, "kb_id": knowledge_id, "tenant_id": tenant_id, })

            created_docs.append({**doc.to_dict(), "task_id": task.id})
            task_ids.append(task.id)
    except ValidationException as e:
        return api_error(str(e))
    except Exception as e:
        logger.exception(f"导入文档异常: {e}")
        return api_error(f"导入文档异常：{str(e)}")

    await kb_service.increment_doc_count(knowledge_id, delta=len(created_docs))

    return api_success(data={
        "knowledge_id": knowledge_id, "doc_list": created_docs, "task_ids": task_ids, })

@router.post("/knowledge/doc/import-template")
async def import_template_documents(
    tenant_id: str | None = Query(None, description="租户ID"), user_id: str | None = Query(None, description="用户ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), kb_service: KnowledgeBaseService = Depends(get_kb_service), doc_service: DocumentService = Depends(get_doc_service), task_service: TaskService = Depends(get_task_service), ):
    """按模板导入文档到知识库

    支持的模板类型：
    - legal: 法律文书
    - contract: 合同范本
    - resume: 简历文档
    - ppt: PPT 幻灯片
    - paper: 论文文档
    - qa: 结构化问答对

    body 示例：
    {{
        "knowledge_id": "kb_xxx", "documents": [
            {{
                "template_type": "legal", "name": "民事判决书.docx", "location": "minio://bucket/cases/2024-001.docx", "size": 51200, "tags": ["民事", "判决"], "parse_options": {{}}
            }}, {{
                "template_type": "contract", "name": "采购合同范本.docx", "location": "minio://bucket/contracts/procurement.docx", "size": 45000, "tags": ["采购", "合同"], "parse_options": {{}}
            }}
        ]
    }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    knowledge_id = body.get("knowledge_id")
    documents = body.get("documents", [])

    if not knowledge_id:
        return api_error("knowledge_id 不能为空")
    if not documents:
        return api_error("documents 不能为空")

    kb = await kb_service.get_by_id(knowledge_id, tenant_id)
    if not kb:
        return api_error("知识库不存在")

    operator = current_operator()
    created_docs = []
    task_ids = []

    try:
        for item_dict in documents:
            item = TemplateDocumentImportItem.model_validate(item_dict)
            doc = await doc_service.create_template_document(
                tenant_id=tenant_id, kb_id=knowledge_id, item=item, created_by=operator, )

            task = await task_service.create(
                tenant_id=tenant_id, kb_id=knowledge_id, doc_id=doc.id, task_type="parse", )

            mq = get_message_queue()
            await mq.produce("jusure:task:parse", {
                "task_id": task.id, "doc_id": doc.id, "kb_id": knowledge_id, "tenant_id": tenant_id, })

            created_docs.append({**doc.to_dict(), "task_id": task.id})
            task_ids.append(task.id)
    except ValidationException as e:
        return api_error(str(e))
    except Exception as e:
        logger.exception(f"模板导入文档异常: {e}")
        return api_error(f"模板导入文档异常：{str(e)}")

    await kb_service.increment_doc_count(knowledge_id, delta=len(created_docs))

    return api_success(data={
        "knowledge_id": knowledge_id, "doc_list": created_docs, "task_ids": task_ids, })

# ============== 用户权限组依赖注入 ==============

def get_perm_group_service(db=Depends(get_db)) -> UserPermGroupService:
    return UserPermGroupService(db)

def get_kb_grant_service(db=Depends(get_db)) -> KBPermGrantService:
    return KBPermGrantService(db)

# ==============================================================
# 用户权限组接口 /ai/permission/group
# 用途：把一批用户打包为一个权限组，再整体授权给知识库或知识库群组
# ==============================================================

@router.post("/permission/group")
async def create_permission_group(
    tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="用户 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """创建用户权限组

    body: {{ "name": "开发团队", "description": "描述" }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    name = body.get("name", "").strip()
    if not name:
        return api_error("name 不能为空")
    operator = current_operator()
    pg = await service.create(
        tenant_id=tenant_id, name=name, description=body.get("description"), created_by=operator, )
    return api_success(data=pg.to_dict())

@router.get("/permission/group")
async def list_permission_groups(
    tenant_id: str | None = Query(None, description="租户 ID"), name: str | None = Query(None, description="权限组名称（模糊查询）"), page_no: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """列出用户权限组"""
    tenant_id = normalize_tenant_id(tenant_id)
    groups, total = await service.list(
        tenant_id=tenant_id, name=name, page=page_no, page_size=page_size, )
    return api_success(data={
        "list": [g.to_dict() for g in groups], "total": total, "page_no": page_no, "page_size": page_size, })

@router.get("/permission/group/{perm_group_id}")
async def get_permission_group(
    perm_group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """获取用户权限组详情"""
    tenant_id = normalize_tenant_id(tenant_id)
    pg = await service.get_by_id(perm_group_id, tenant_id)
    if not pg:
        return api_error("权限组不存在")
    return api_success(data=pg.to_dict())

@router.put("/permission/group/{perm_group_id}")
async def update_permission_group(
    perm_group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """更新用户权限组名称/描述"""
    tenant_id = normalize_tenant_id(tenant_id, body)
    try:
        pg = await service.update(
            perm_group_id=perm_group_id, tenant_id=tenant_id, name=body.get("name"), description=body.get("description"), )
        return api_success(data=pg.to_dict())
    except NotFoundException:
        return api_error("权限组不存在")

@router.delete("/permission/group/{perm_group_id}")
async def delete_permission_group(
    perm_group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """删除用户权限组（同时清除成员关联和授权记录）"""
    tenant_id = normalize_tenant_id(tenant_id)
    try:
        await service.delete(perm_group_id, tenant_id)
        return api_success(data={"perm_group_id": perm_group_id})
    except NotFoundException:
        return api_error("权限组不存在")

# ---------- 用户权限组成员管理 ----------

@router.get("/permission/group/{perm_group_id}/members")
async def list_permission_group_members(
    perm_group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """列出权限组成员"""
    tenant_id = normalize_tenant_id(tenant_id)
    pg = await service.get_by_id(perm_group_id, tenant_id)
    if not pg:
        return api_error("权限组不存在")
    members = await service.list_members(perm_group_id)
    return api_success(data={
        "list": [m.to_dict() for m in members], "total": len(members), })

@router.post("/permission/group/{perm_group_id}/members")
async def add_permission_group_member(
    perm_group_id: str, tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """添加用户到权限组

    body: {{ "user_id": "u001" }} 或 {{ "user_ids": ["u001", "u002"] }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    pg = await service.get_by_id(perm_group_id, tenant_id)
    if not pg:
        return api_error("权限组不存在")

    # 支持单个或批量
    user_ids: list[str] = body.get("user_ids") or []
    single = body.get("user_id", "").strip()
    if single:
        user_ids = [single]
    if not user_ids:
        return api_error("user_id 或 user_ids 不能为空")

    added = []
    for uid in user_ids:
        m = await service.add_member(perm_group_id, tenant_id, uid)
        added.append(m.to_dict())
    return api_success(data={"added": added, "total": len(added)})

@router.delete("/permission/group/{perm_group_id}/members/{target_user_id}")
async def remove_permission_group_member(
    perm_group_id: str, target_user_id: str, tenant_id: str | None = Query(None, description="租户 ID"), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """从权限组移除用户"""
    tenant_id = normalize_tenant_id(tenant_id)
    pg = await service.get_by_id(perm_group_id, tenant_id)
    if not pg:
        return api_error("权限组不存在")
    removed = await service.remove_member(perm_group_id, target_user_id)
    if not removed:
        return api_error("该用户不在权限组中")
    return api_success(data={"perm_group_id": perm_group_id, "user_id": target_user_id})

@router.get("/permission/user/{user_id}/groups")
async def get_user_permission_groups(
    user_id: str, tenant_id: str | None = Query(None, description="租户 ID"), service: UserPermGroupService = Depends(get_perm_group_service), ):
    """查询用户所属的所有权限组"""
    tenant_id = normalize_tenant_id(tenant_id)
    groups = await service.list_user_perm_groups(tenant_id, user_id)
    return api_success(data={
        "list": [g.to_dict() for g in groups], "total": len(groups), })

# ==============================================================
# 授权接口 /ai/permission/grant
# 将「用户」或「用户权限组」授权给「知识库」或「知识库群组」
# ==============================================================

@router.post("/permission/grant")
async def grant_permission(
    tenant_id: str | None = Query(None, description="租户 ID"), user_id: str | None = Query(None, description="操作者 ID"), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), service: KBPermGrantService = Depends(get_kb_grant_service), ):
    """授权或更新授权（UPSERT 语义）

    body 示例：
    {{
        "subject_type": "perm_group", // user 或 perm_group
        "subject_id": "upg_xxx", "target_type": "kb_group", // kb 或 kb_group
        "target_id": "kg_yyy", "role": "member"                  // owner/admin/member/viewer
    }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    subject_type = body.get("subject_type", "").strip()
    subject_id = body.get("subject_id", "").strip()
    target_type = body.get("target_type", "").strip()
    target_id = body.get("target_id", "").strip()
    role = body.get("role", "viewer").strip()

    if not all([subject_type, subject_id, target_type, target_id]):
        return api_error("subject_type, subject_id, target_type, target_id 均不能为空")

    operator = current_operator()
    try:
        grant = await service.grant(
            tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id, target_type=target_type, target_id=target_id, role=role, created_by=operator, )
        return api_success(data=grant.to_dict())
    except ValidationException as e:
        return api_error(str(e))

@router.delete("/permission/grant")
async def revoke_permission(
    tenant_id: str | None = Query(None, description="租户 ID"), body: dict[str, Any] = Body(...), service: KBPermGrantService = Depends(get_kb_grant_service), ):
    """撒销授权

    body: {{ "subject_type": "perm_group", "subject_id": "...", "target_type": "kb", "target_id": "..." }}
    """
    tenant_id = normalize_tenant_id(tenant_id, body)
    subject_type = body.get("subject_type", "").strip()
    subject_id = body.get("subject_id", "").strip()
    target_type = body.get("target_type", "").strip()
    target_id = body.get("target_id", "").strip()

    if not all([subject_type, subject_id, target_type, target_id]):
        return api_error("subject_type, subject_id, target_type, target_id 均不能为空")

    removed = await service.revoke(subject_type, subject_id, target_type, target_id)
    if not removed:
        return api_error("授权记录不存在")
    return api_success(data={"revoked": True})

@router.get("/permission/grant/target")
async def list_grants_on_target(
    target_type: str = Query(..., description="目标类型：kb / kb_group"), target_id: str = Query(..., description="目标 ID"), tenant_id: str | None = Query(None, description="租户 ID"), service: KBPermGrantService = Depends(get_kb_grant_service), ):
    """查询某个目标的所有授权列表"""
    tenant_id = normalize_tenant_id(tenant_id)
    grants = await service.list_grants_on_target(
        target_type=target_type, target_id=target_id, tenant_id=tenant_id, )
    return api_success(data={
        "list": [g.to_dict() for g in grants], "total": len(grants), })

@router.get("/permission/grant/subject")
async def list_grants_by_subject(
    subject_type: str = Query(..., description="主体类型：user / perm_group"), subject_id: str = Query(..., description="主体 ID"), tenant_id: str | None = Query(None, description="租户 ID"), service: KBPermGrantService = Depends(get_kb_grant_service), ):
    """查询某个主体拥有的所有授权列表"""
    tenant_id = normalize_tenant_id(tenant_id)
    grants = await service.list_grants_by_subject(
        subject_type=subject_type, subject_id=subject_id, tenant_id=tenant_id, )
    return api_success(data={
        "list": [g.to_dict() for g in grants], "total": len(grants), })

@router.get("/permission/user/{user_id}/effective-role")
async def get_user_effective_role(
    user_id: str, target_type: str = Query(..., description="目标类型：kb / kb_group"), target_id: str = Query(..., description="目标 ID"), tenant_id: str | None = Query(None, description="租户 ID"), service: KBPermGrantService = Depends(get_kb_grant_service), ):
    """查询用户对指定目标的有效角色（直接授权 + 权限组授权取最高级别）"""
    tenant_id = normalize_tenant_id(tenant_id)
    effective = await service.get_effective_role(
        user_id=user_id, target_type=target_type, target_id=target_id, tenant_id=tenant_id, )
    return api_success(data={
        "user_id": user_id, "target_type": target_type, "target_id": target_id, "effective_role": effective, "has_access": effective is not None, })

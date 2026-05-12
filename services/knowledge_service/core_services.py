# -*- coding: utf-8 -*-
"""
知识库服务 - 核心业务逻辑
参考 ragflow 的 KnowledgebaseService 设计
"""
from typing import Any
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from common.models import (
    KnowledgeBaseModel, DocumentModel, TaskModel, KnowledgeBaseCreate, KnowledgeBaseUpdate, DocumentCreate, TextDocParseOptions, TableDocParseOptions, WebDocParseOptions, ImageDocParseOptions, AudioDocParseOptions, DocumentImportItem, TemplateDocumentImportItem, TaskStatus, DocumentStatus, StatusEnum, KnowledgeGroupModel, KnowledgeGroupMemberModel, UserPermissionGroupModel, UserPermissionGroupMemberModel, KBPermissionGrantModel, )
from common.utils import (
    generate_id, NotFoundException, ValidationException, get_logger, now_timestamp
)

logger = get_logger("knowledge_service")
DEFAULT_TENANT_ID = "default"

# ============== scope <-> permission 映射 ==============
# jusure_AI 用 scope 整数表示权限：0=公共, 1=个人, 2=私有场景
# microservices ORM 用 permission 字符串：team / me

SCOPE_TO_PERMISSION: dict[int, str] = {
    0: "team", # 公共知识库 → team（同租户可见）
    1: "me", # 个人知识库 → me
    2: "me", # 私有知识库 → me（场景私有，暂映射到 me）
}
PERMISSION_TO_SCOPE: dict[str, int] = {
    "team": 0, "me": 1, }

def scope_to_permission(scope: int) -> str:
    """将 jusure_AI scope 整数转换为 ORM permission 字符串"""
    return SCOPE_TO_PERMISSION.get(scope, "team")

def permission_to_scope(permission: str) -> int:
    """将 ORM permission 字符串转换为 jusure_AI scope 整数"""
    return PERMISSION_TO_SCOPE.get(permission, 0)

class KnowledgeBaseService:
    """知识库服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self, tenant_id: str | None, data: KnowledgeBaseCreate, created_by: str | None = None
    ) -> KnowledgeBaseModel:
        """创建知识库（接受对齐后的 Schema，内部映射到 ORM 字段）"""
        tenant = tenant_id or DEFAULT_TENANT_ID
        kb = KnowledgeBaseModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("kb"), tenant_id=tenant, name=data.knowledge_name, description=data.knowledge_desc, language=data.language, permission=scope_to_permission(data.scope), embedding_model_id=data.aigc_model_id, parser_id=data.parser_id, parser_config=data.parser_config, graph_enabled=data.graph_enable, group_id=data.group_id, created_by=created_by, status=StatusEnum.ACTIVE.value
        )

        self.session.add(kb)
        await self.session.flush()

        logger.info(f"Created knowledge base: {kb.id}, name: {kb.name}")
        return kb
    
    async def get_by_id(self, kb_id: str, tenant_id: str | None = None) -> KnowledgeBaseModel | None:
        """获取知识库详情"""
        conditions = [
            KnowledgeBaseModel.id == kb_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value
        ]
        if tenant_id:
            conditions.append(KnowledgeBaseModel.tenant_id == tenant_id)
        stmt = select(KnowledgeBaseModel).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list(
        self, tenant_id: str | None, user_id: str | None = None, scope: int | None = None, page: int = 1, page_size: int = 10, name: str | None = None, status: str | None = None, order_by: str = "create_time", desc: bool = True, group_id: str | None = None, ) -> tuple[list[KnowledgeBaseModel], int]:
        """获取知识库列表（含权限过滤 + scope 过滤）

        可见规则（参考 RAGflow）：
        - user_id 创建的全部知识库（无论 permission 值）
        - 同 tenant_id 下 permission='team' 的知识库（其他成员的团队库）
        - 若 user_id 为 None，退化为仅按 tenant_id 过滤（内部/系统调用）
        - scope 不为 None 时，额外按 permission 过滤（scope→permission 映射）
        """
        base_filter = KnowledgeBaseModel.status != StatusEnum.DELETED.value

        if user_id:
            # 自己创建的全部 OR 同租户的 team 知识库
            permission_filter = or_(
                KnowledgeBaseModel.created_by == user_id, (KnowledgeBaseModel.tenant_id == tenant_id) &
                (KnowledgeBaseModel.permission == "team")
            )
            stmt = select(KnowledgeBaseModel).where(base_filter, permission_filter)
        else:
            # 无 user_id 时，退化为仅按 tenant_id 过滤（兼容旧调用）
            stmt = select(KnowledgeBaseModel).where(
                KnowledgeBaseModel.tenant_id == tenant_id, base_filter
            )

        # scope 过滤：将外部 scope 整数转换为 ORM permission 字符串过滤
        if scope is not None:
            target_permission = scope_to_permission(scope)
            stmt = stmt.where(KnowledgeBaseModel.permission == target_permission)

        if name:
            stmt = stmt.where(KnowledgeBaseModel.name.like(f"%{name}%"))

        if status:
            stmt = stmt.where(KnowledgeBaseModel.status == status)
        
        # group_id 过滤
        if group_id:
            stmt = stmt.where(KnowledgeBaseModel.group_id == group_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0

        order_column = getattr(KnowledgeBaseModel, order_by, KnowledgeBaseModel.create_time)
        if desc:
            stmt = stmt.order_by(order_column.desc())
        else:
            stmt = stmt.order_by(order_column.asc())

        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        kbs = result.scalars().all()

        return list(kbs), total

    
    async def update(
        self, kb_id: str, tenant_id: str | None, data: KnowledgeBaseUpdate
    ) -> KnowledgeBaseModel:
        """更新知识库（接受对齐后的 Schema，内部映射到 ORM 字段）"""
        kb = await self.get_by_id(kb_id, tenant_id)
        if not kb:
            raise NotFoundException("Knowledge base", kb_id)

        update_data = data.model_dump(exclude_unset=True)
        # 字段名映射：Schema → ORM
        field_mapping = {
            "knowledge_name": "name", "knowledge_desc": "description", "graph_enable": "graph_enabled", }
        for schema_key, value in update_data.items():
            if schema_key == "scope":
                # scope 整数 → permission 字符串
                kb.permission = scope_to_permission(value)
            elif schema_key == "status":
                # status: 0=禁用→"0", 1=启用→"1"
                kb.status = str(value)
            else:
                orm_key = field_mapping.get(schema_key, schema_key)
                setattr(kb, orm_key, value)

        kb.update_time = now_timestamp()
        await self.session.flush()

        logger.info(f"Updated knowledge base: {kb_id}")
        return kb
    
    async def delete(self, kb_id: str, tenant_id: str | None, user_id: str | None = None) -> bool:
        """删除知识库 (软删除)

        权限规则：
        - 若 user_id 不为空，只允许创建人（created_by == user_id）删除
        - 否则仅校验 tenant_id（兼容内部调用）
        """
        kb = await self.get_by_id(kb_id, tenant_id)
        if not kb:
            raise NotFoundException("Knowledge base", kb_id)
        
        if user_id and kb.created_by and kb.created_by != user_id:
            raise ValidationException(
                f"Permission denied: only the creator can delete knowledge base '{kb_id}'"
            )
        
        kb.status = StatusEnum.DELETED.value
        kb.update_time = now_timestamp()
        await self.session.flush()
        
        logger.info(f"Deleted knowledge base: {kb_id} by user: {user_id or 'system'}")
        return True
    
    async def increment_doc_count(self, kb_id: str, delta: int = 1):
        """增加文档计数"""
        stmt = update(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == kb_id
        ).values(
            doc_num=KnowledgeBaseModel.doc_num + delta, update_time=now_timestamp()
        )
        await self.session.execute(stmt)
    
    async def increment_chunk_count(self, kb_id: str, delta: int = 1, token_delta: int = 0):
        """增加切片计数"""
        stmt = update(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == kb_id
        ).values(
            chunk_count=KnowledgeBaseModel.chunk_count + delta, token_num=KnowledgeBaseModel.token_num + token_delta, update_time=now_timestamp()
        )
        await self.session.execute(stmt)

class DocumentService:
    """文档服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self, tenant_id: str | None, kb_id: str, data: DocumentCreate, content_hash: str | None = None
    ) -> DocumentModel:
        """创建文档"""
        tenant = tenant_id or DEFAULT_TENANT_ID
        doc = DocumentModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("doc"), tenant_id=tenant, kb_id=kb_id, name=data.name, type=data.type, size=data.size, location=data.location, parser_id=data.parser_id, parser_config=data.parser_config, source_type=data.source_type, source_url=data.source_url, content_hash=content_hash, status=DocumentStatus.PENDING.value
        )
        
        self.session.add(doc)
        await self.session.flush()
        
        logger.info(f"Created document: {doc.id}, name: {doc.name}")
        return doc
    
    async def get_by_id(self, doc_id: str) -> DocumentModel | None:
        """获取文档详情"""
        stmt = select(DocumentModel).where(DocumentModel.id == doc_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_by_kb(
        self, kb_id: str, page: int = 1, page_size: int = 10, status: str | None = None, name: str | None = None
    ) -> tuple[list[DocumentModel], int]:
        """获取知识库下的文档列表"""
        stmt = select(DocumentModel).where(DocumentModel.kb_id == kb_id)
        
        if status:
            stmt = stmt.where(DocumentModel.status == status)
        
        if name:
            stmt = stmt.where(DocumentModel.name.like(f"%{name}%"))
        
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        
        stmt = stmt.order_by(DocumentModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.session.execute(stmt)
        docs = result.scalars().all()
        
        return list(docs), total

    async def list(
        self, page: int = 1, page_size: int = 10, kb_id: str | None = None, tenant_id: str | None = None, status: str | None = None, name: str | None = None,
    ) -> tuple[list[DocumentModel], int]:
        """获取文档列表，供上传历史等跨知识库接口使用。"""
        stmt = select(DocumentModel)
        if kb_id:
            stmt = stmt.where(DocumentModel.kb_id == kb_id)
        if tenant_id:
            stmt = stmt.where(DocumentModel.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(DocumentModel.status == status)
        if name:
            stmt = stmt.where(DocumentModel.name.like(f"%{name}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0

        stmt = stmt.order_by(DocumentModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
    
    async def update_progress(
        self, doc_id: str, progress: float, progress_msg: str = "", status: str | None = None
    ):
        """更新文档处理进度"""
        doc = await self.get_by_id(doc_id)
        if not doc:
            return
        
        doc.progress = progress
        doc.progress_msg = progress_msg
        if status:
            doc.status = status
        doc.update_time = now_timestamp()
        await self.session.flush()
    
    async def update_status(self, doc_id: str, status: str, error_msg: str = ""):
        """更新文档状态"""
        doc = await self.get_by_id(doc_id)
        if not doc:
            return
        
        doc.status = status
        if error_msg:
            doc.progress_msg = error_msg
        doc.update_time = now_timestamp()
        await self.session.flush()
    
    async def delete(self, doc_id: str) -> bool:
        """删除文档"""
        doc = await self.get_by_id(doc_id)
        if not doc:
            return False
        
        await self.session.delete(doc)
        await self.session.flush()
        
        logger.info(f"Deleted document: {doc_id}")
        return True
    
    async def create_imported_document(
        self, tenant_id: str | None, kb_id: str, item: DocumentImportItem, parser_id: str = "naive", created_by: str | None = None, ) -> DocumentModel:
        """按精细化导入参数创建文档

        1. 根据 doc_category 校验 parse_options 结构
        2. 构造 parser_config（合并 parse_options + 通用字段）
        3. 创建 DocumentModel 并持久化
        """
        category = item.doc_category.lower().strip()
        valid_categories = {"text", "table", "web", "image", "audio"}
        if category not in valid_categories:
            raise ValidationException(
                f"Invalid doc_category '{item.doc_category}'. Must be one of: {valid_categories}"
            )

        # 根据类型校验 parse_options
        opts = item.parse_options or {}
        validated: BaseModel
        if category == "text":
            validated = TextDocParseOptions.model_validate(opts)
        elif category == "table":
            validated = TableDocParseOptions.model_validate(opts)
        elif category == "web":
            validated = WebDocParseOptions.model_validate(opts)
        elif category == "image":
            validated = ImageDocParseOptions.model_validate(opts)
        elif category == "audio":
            validated = AudioDocParseOptions.model_validate(opts)
        else:
            raise ValidationException(
                f"Invalid doc_category '{item.doc_category}'. Must be one of: {valid_categories}"
            )

        parser_config = validated.model_dump()
        # 参数名映射：前端/模型字段 → 解析器消费字段
        _import_param_map = {
            "chunk_size": "chunk_token_num", }
        for old_key, new_key in _import_param_map.items():
            if old_key in parser_config:
                parser_config[new_key] = parser_config.pop(old_key)
        # 注入通用字段，供 task_executor 消费时识别
        parser_config["doc_category"] = category
        parser_config["tags"] = item.tags

        # image/audio 类型自动映射到对应解析器
        effective_parser_id = parser_id
        if category in ("image", "audio"):
            effective_parser_id = category

        doc = DocumentModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("doc"), tenant_id=tenant_id or DEFAULT_TENANT_ID, kb_id=kb_id, name=item.name, type=category, size=item.size, location=item.location, doc_category=category, tags=item.tags, source_url=item.source_url, parser_id=effective_parser_id, parser_config=parser_config, source_type="local", status=DocumentStatus.PENDING.value, )
        self.session.add(doc)
        await self.session.flush()
        logger.info(
            f"Created imported document: {doc.id}, category={category}, name={item.name}"
        )
        return doc

    async def create_template_document(
        self, tenant_id: str | None, kb_id: str, item: TemplateDocumentImportItem, created_by: str | None = None, ) -> DocumentModel:
        """按模板导入参数创建文档

        支持的模板类型：
        - legal: 法律文书
        - contract: 合同范本
        - resume: 简历文档
        - ppt: PPT 幻灯片
        - paper: 论文文档
        - qa: 结构化问答对
        """
        template_type = item.template_type.lower().strip()
        valid_templates = {"legal", "contract", "resume", "ppt", "paper", "qa"}
        if template_type not in valid_templates:
            raise ValidationException(
                f"Invalid template_type '{item.template_type}'. Must be one of: {valid_templates}"
            )

        # 文件扩展名校验（ppt 实际映射到 pptx 解析器，但文件可以是 pptx）
        ext = (item.name.rsplit(".", 1)[-1] if "." in item.name else "").lower()
        if template_type == "ppt" and ext not in {"ppt", "pptx"}:
            raise ValidationException(
                f"Template 'ppt' requires file extension .ppt or .pptx, got '.{ext}'"
            )

        parser_config = dict(item.parse_options or {})
        parser_config["template_type"] = template_type
        parser_config["tags"] = item.tags

        # 推断文档类型（用于存储和展示）
        doc_type = ext if ext else "unknown"

        doc = DocumentModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("doc"), tenant_id=tenant_id or DEFAULT_TENANT_ID, kb_id=kb_id, name=item.name, type=doc_type, size=item.size, location=item.location, doc_category="text", template_type=template_type, tags=item.tags, parser_id=template_type, parser_config=parser_config, source_type="local", status=DocumentStatus.PENDING.value, )
        self.session.add(doc)
        await self.session.flush()
        logger.info(
            f"Created template document: {doc.id}, template={template_type}, name={item.name}"
        )
        return doc
    
    async def run(self, doc_id: str) -> bool:
        """启动文档处理"""
        doc = await self.get_by_id(doc_id)
        if not doc:
            raise NotFoundException("Document", doc_id)
        
        doc.run = "1"
        doc.status = DocumentStatus.PENDING.value
        doc.progress = 0
        doc.progress_msg = ""
        doc.update_time = now_timestamp()
        await self.session.flush()
        
        return True
    
    async def stop(self, doc_id: str) -> bool:
        """停止文档处理"""
        doc = await self.get_by_id(doc_id)
        if not doc:
            return False
        
        doc.run = "0"
        doc.update_time = now_timestamp()
        await self.session.flush()
        
        return True

class TaskService:
    """任务服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self, tenant_id: str | None, kb_id: str, doc_id: str, task_type: str = "parse", priority: int = 0, from_page: int = 0, to_page: int = 100000000
    ) -> TaskModel:
        """创建任务"""
        task = TaskModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("task"), tenant_id=tenant_id or DEFAULT_TENANT_ID, kb_id=kb_id, doc_id=doc_id, task_type=task_type, priority=priority, from_page=from_page, to_page=to_page, status=TaskStatus.PENDING.value
        )
        
        self.session.add(task)
        await self.session.flush()
        
        logger.info(f"Created task: {task.id}, type: {task_type}")
        return task
    
    async def get_by_id(self, task_id: str) -> dict[str, Any] | None:
        """获取任务详情 (包含关联的文档和知识库信息)"""
        stmt = select(TaskModel, DocumentModel, KnowledgeBaseModel).join(
            DocumentModel, TaskModel.doc_id == DocumentModel.id
        ).join(
            KnowledgeBaseModel, TaskModel.kb_id == KnowledgeBaseModel.id
        ).where(TaskModel.id == task_id)
        
        result = await self.session.execute(stmt)
        row = result.first()
        
        if not row:
            return None
        
        task, doc, kb = row
        task_dict = task.to_dict()
        task_dict["doc_name"] = doc.name
        task_dict["doc_type"] = doc.type
        task_dict["doc_location"] = doc.location
        task_dict["kb_name"] = kb.name
        task_dict["embedding_model_id"] = kb.embedding_model_id
        task_dict["embedding_model_path"] = kb.embedding_model_path
        task_dict["parser_id"] = kb.parser_id
        task_dict["parser_config"] = kb.parser_config
        
        return task_dict
    
    async def get_pending_tasks(
        self, limit: int = 100, task_type: str | None = None
    ) -> list[TaskModel]:
        """获取待处理任务"""
        stmt = select(TaskModel).where(
            TaskModel.status == TaskStatus.PENDING.value
        )
        
        if task_type:
            stmt = stmt.where(TaskModel.task_type == task_type)
        
        stmt = stmt.order_by(
            TaskModel.priority.desc(), TaskModel.create_time.asc()
        ).limit(limit)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def update_progress(
        self, task_id: str, progress: float, progress_msg: str = ""
    ):
        """更新任务进度"""
        stmt = update(TaskModel).where(
            TaskModel.id == task_id
        ).values(
            progress=progress, progress_msg=progress_msg, update_time=now_timestamp()
        )
        await self.session.execute(stmt)
    
    async def mark_running(self, task_id: str):
        """标记任务为运行中"""
        stmt = update(TaskModel).where(
            TaskModel.id == task_id
        ).values(
            status=TaskStatus.RUNNING.value, update_time=now_timestamp()
        )
        await self.session.execute(stmt)
    
    async def mark_completed(self, task_id: str, result: dict | None = None):
        """标记任务完成"""
        stmt = update(TaskModel).where(
            TaskModel.id == task_id
        ).values(
            status=TaskStatus.COMPLETED.value, progress=1.0, progress_msg="Completed", result=result, update_time=now_timestamp()
        )
        await self.session.execute(stmt)
    
    async def mark_failed(self, task_id: str, error_msg: str):
        """标记任务失败"""
        task = await self.session.get(TaskModel, task_id)
        if not task:
            return
        
        retry_count = task.retry_count + 1
        
        stmt = update(TaskModel).where(
            TaskModel.id == task_id
        ).values(
            status=TaskStatus.FAILED.value if retry_count >= 3 else TaskStatus.PENDING.value, retry_count=retry_count, error_msg=error_msg, progress_msg=f"Failed (retry {retry_count})", update_time=now_timestamp()
        )
        await self.session.execute(stmt)
    
    async def delete_by_doc(self, doc_id: str):
        """删除文档相关的所有任务"""
        stmt = delete(TaskModel).where(TaskModel.doc_id == doc_id)
        await self.session.execute(stmt)

class KnowledgeExtService:
    """知识库扩展服务（处理高优先级缺失接口）"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(
        self, tenant_id: str | None, scope: int | None = None, name: str | None = None, page: int = 1, page_size: int = 50, group_id: str | None = None, ) -> tuple[list[KnowledgeBaseModel], int]:
        """全量知识库查询（不做权限过滤，仅按 tenant_id），对应 /ai/knowledge/all"""
        stmt = select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.tenant_id == tenant_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value, )
        if scope is not None:
            target_permission = scope_to_permission(scope)
            stmt = stmt.where(KnowledgeBaseModel.permission == target_permission)
        if name:
            stmt = stmt.where(KnowledgeBaseModel.name.like(f"%{name}%"))
        
        # group_id 过滤
        if group_id:
            stmt = stmt.where(KnowledgeBaseModel.group_id == group_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0

        stmt = stmt.order_by(KnowledgeBaseModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        kbs = result.scalars().all()
        return list(kbs), total

    async def get_tree(
        self, tenant_id: str | None, scope: int | None = None, name: str | None = None, page: int = 1, page_size: int = 1000, ) -> dict[str, Any]:
        """知识库树形结构，对应 /ai/knowledge/tree
        
        当前版本：所有知识库以平铺列表返回（无目录层级），可后续扩展。
        """
        kbs, total = await self.list_all(
            tenant_id=tenant_id, scope=scope, name=name, page=page, page_size=page_size, )
        items = []
        for kb in kbs:
            d = kb.to_dict()
            d["type"] = "knowledge"
            d["children"] = []
            items.append(d)
        return {"list": items, "total": total, "page_no": page, "page_size": page_size}

    async def list_docs_by_date(
        self, knowledge_id: str, start_time: str | None = None, end_time: str | None = None, doc_name: str | None = None, state: str | None = None, page: int = 1, page_size: int = 20, ) -> tuple[list[DocumentModel], int]:
        """按时间段/名称查询文档，对应 /ai/knowledge/doc/update GET"""
        stmt = select(DocumentModel).where(DocumentModel.kb_id == knowledge_id)
        if doc_name:
            stmt = stmt.where(DocumentModel.name.like(f"%{doc_name}%"))
        if state:
            stmt = stmt.where(DocumentModel.status == state)
        if start_time:
            from datetime import datetime as _dt
            try:
                ts = int(_dt.fromisoformat(start_time).timestamp() * 1000)
                stmt = stmt.where(DocumentModel.create_time >= ts)
            except Exception:
                pass
        if end_time:
            from datetime import datetime as _dt
            try:
                ts = int(_dt.fromisoformat(end_time).timestamp() * 1000)
                stmt = stmt.where(DocumentModel.create_time <= ts)
            except Exception:
                pass

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(DocumentModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        docs = result.scalars().all()
        return list(docs), total

    async def batch_delete_docs(
        self, knowledge_id: str, doc_ids: list[str] | None = None, start_time: str | None = None, end_time: str | None = None, key_chose: str = "doc_ids", ) -> int:
        """批量删除文档（按 doc_ids 或时间段），对应 /ai/knowledge/doc/update DELETE"""
        if key_chose == "doc_ids" and doc_ids:
            stmt = delete(DocumentModel).where(
                DocumentModel.kb_id == knowledge_id, DocumentModel.id.in_(doc_ids), )
        else:
            stmt = delete(DocumentModel).where(DocumentModel.kb_id == knowledge_id)
            if start_time:
                from datetime import datetime as _dt
                try:
                    ts = int(_dt.fromisoformat(start_time).timestamp() * 1000)
                    stmt = stmt.where(DocumentModel.create_time >= ts)
                except Exception:
                    pass
            if end_time:
                from datetime import datetime as _dt
                try:
                    ts = int(_dt.fromisoformat(end_time).timestamp() * 1000)
                    stmt = stmt.where(DocumentModel.create_time <= ts)
                except Exception:
                    pass
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def batch_continue_handle(
        self, tenant_id: str | None, knowledge_id: str, doc_list: list[dict[str, Any]], ) -> dict[str, Any]:
        """批量继续处理文档（入库+重新发任务），对应 /ai/knowledge/doc/batch/continue/handle"""
        task_svc = TaskService(self.session)

        # 实际走 MQ 入队
        from common.storage import get_message_queue
        mq_client = get_message_queue()

        queued = []
        failed = []
        for doc_item in doc_list:
            doc_id = doc_item.get("document_id") or doc_item.get("doc_id")
            if not doc_id:
                failed.append({"doc_item": doc_item, "reason": "missing document_id"})
                continue
            # 查询文档
            stmt = select(DocumentModel).where(DocumentModel.id == doc_id)
            result = await self.session.execute(stmt)
            doc = result.scalar_one_or_none()
            if not doc:
                failed.append({"doc_id": doc_id, "reason": "document not found"})
                continue

            # 重置状态为 pending
            doc.status = DocumentStatus.PENDING.value
            doc.progress = 0.0
            doc.progress_msg = ""
            doc.run = "1"
            doc.update_time = now_timestamp()

            # 发解析任务
            task = await task_svc.create(
                tenant_id=tenant_id, kb_id=knowledge_id, doc_id=doc_id, task_type="parse", )
            try:
                await mq_client.produce("jusure:task:parse", {
                    "task_id": task.id, "doc_id": doc_id, "kb_id": knowledge_id, "tenant_id": tenant_id, "parser_config": doc_item.get("parser_config", {}), })
            except Exception as e:
                logger.warning(f"MQ produce failed for doc {doc_id}: {e}")

            queued.append({"doc_id": doc_id, "task_id": task.id})

        await self.session.flush()
        return {"queued": queued, "failed": failed, "total": len(doc_list)}

# ============== 角色层级 ==============

ROLE_HIERARCHY: dict[str, int] = {
    "owner": 4, "admin": 3, "member": 2, "viewer": 1, }

class KnowledgeGroupService:
    """知识库群组服务 - 支持无限层级的树形组织架构"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 群组 CRUD ----------

    async def create(
        self, tenant_id: str | None, name: str, description: str | None = None, parent_id: str | None = None, created_by: str | None = None, ) -> KnowledgeGroupModel:
        """创建群组，自动计算 path 和 depth"""
        tenant = tenant_id or DEFAULT_TENANT_ID
        depth = 0
        path = ""

        if parent_id:
            parent = await self.get_by_id(parent_id, tenant)
            if not parent:
                raise NotFoundException("KnowledgeGroup", parent_id)
            depth = parent.depth + 1
            path = parent.path

        group = KnowledgeGroupModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("kg"), tenant_id=tenant, name=name, description=description, parent_id=parent_id, depth=depth, status=StatusEnum.ACTIVE.value, created_by=created_by, )
        self.session.add(group)
        await self.session.flush()  # 获取 id

        # 更新 path：格式 /parent_path/self_id/
        group.path = path + f"/{group.id}/"
        await self.session.flush()

        # 创建者自动成为 owner
        if created_by:
            await self.add_member(group.id, tenant, created_by, "owner")

        logger.info(f"Created knowledge group: {group.id}, name: {name}, depth: {depth}")
        return group

    async def _get_group_by_id_without_tenant(
        self, group_id: str
    ) -> KnowledgeGroupModel | None:
        """不限制 tenant_id 查找群组（内部使用）"""
        conditions = [
            KnowledgeGroupModel.id == group_id, KnowledgeGroupModel.status != StatusEnum.DELETED.value, ]
        stmt = select(KnowledgeGroupModel).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(
        self, group_id: str, tenant_id: str | None = None
    ) -> KnowledgeGroupModel | None:
        """获取群组详情"""
        conditions = [
            KnowledgeGroupModel.id == group_id, KnowledgeGroupModel.status != StatusEnum.DELETED.value, ]
        if tenant_id:
            conditions.append(
                or_(
                    KnowledgeGroupModel.tenant_id == tenant_id, KnowledgeGroupModel.tenant_id == "default"
                )
            )
        stmt = select(KnowledgeGroupModel).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_validation(
        self, group_id: str, tenant_id: str | None = None
    ) -> KnowledgeGroupModel:
        """获取群组详情，并验证租户权限
        
        :raises NotFoundException: 群组不存在
        :raises ValidationException: 群组不属于该租户
        """
        # 先不限制 tenant_id 查找
        group = await self._get_group_by_id_without_tenant(group_id)
        if not group:
            raise NotFoundException("KnowledgeGroup", group_id)
        
        # 检查 tenant_id 是否匹配
        if tenant_id and tenant_id != "default" and group.tenant_id != "default" and group.tenant_id != tenant_id:
            raise ValidationException(f"群组 {group_id} 不属于租户 {tenant_id}")
        
        return group

    async def list_roots(
        self, tenant_id: str | None, name: str | None = None, page: int = 1, page_size: int = 20, ) -> tuple[list[KnowledgeGroupModel], int]:
        """列出根级群组（parent_id IS NULL）"""
        conditions = [
            KnowledgeGroupModel.parent_id.is_(None), KnowledgeGroupModel.status != StatusEnum.DELETED.value, ]
        if tenant_id:
            conditions.append(
                or_(
                    KnowledgeGroupModel.tenant_id == tenant_id, KnowledgeGroupModel.tenant_id == "default"
                )
            )
        stmt = select(KnowledgeGroupModel).where(*conditions)
        if name:
            stmt = stmt.where(KnowledgeGroupModel.name.like(f"%{name}%"))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(KnowledgeGroupModel.create_time.asc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_all(
        self, tenant_id: str | None, name: str | None = None, page: int = 1, page_size: int = 20, ) -> tuple[list[dict[str, Any]], int]:
        """列出该租户的所有群组（包括根群组和子群组），并附加每个群组下的知识库数量"""
        # 查询群组列表
        conditions = [
            KnowledgeGroupModel.status != StatusEnum.DELETED.value, ]
        if tenant_id:
            conditions.append(
                or_(
                    KnowledgeGroupModel.tenant_id == tenant_id, KnowledgeGroupModel.tenant_id == "default"
                )
            )
        stmt = select(KnowledgeGroupModel).where(*conditions)
        if name:
            stmt = stmt.where(KnowledgeGroupModel.name.like(f"%{name}%"))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(KnowledgeGroupModel.create_time.asc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        groups = list(result.scalars().all())
        
        # 批量查询每个群组下的知识库数量
        group_ids = [g.id for g in groups]
        kb_count_map = {}
        if group_ids:
            kb_count_stmt = select(
                KnowledgeBaseModel.group_id, func.count().label('kb_count')
            ).where(
                KnowledgeBaseModel.group_id.in_(group_ids), KnowledgeBaseModel.status != StatusEnum.DELETED.value, ).group_by(KnowledgeBaseModel.group_id)
            kb_count_result = await self.session.execute(kb_count_stmt)
            kb_count_map = {row.group_id: row.kb_count for row in kb_count_result}
        
        # 组装返回数据
        result_list = []
        for group in groups:
            group_dict = group.to_dict()
            group_dict['kb_count'] = kb_count_map.get(group.id, 0)
            result_list.append(group_dict)
        
        return result_list, total

    async def list_children(
        self, parent_id: str, tenant_id: str | None, ) -> list[KnowledgeGroupModel]:
        """列出直接子群组"""
        conditions = [
            KnowledgeGroupModel.parent_id == parent_id, KnowledgeGroupModel.status != StatusEnum.DELETED.value, ]
        if tenant_id:
            conditions.append(
                or_(
                    KnowledgeGroupModel.tenant_id == tenant_id, KnowledgeGroupModel.tenant_id == "default"
                )
            )
        stmt = select(KnowledgeGroupModel).where(*conditions).order_by(KnowledgeGroupModel.create_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_tree(
        self, tenant_id: str | None, root_id: str | None = None, include_kbs: bool = True, ) -> list[dict[str, Any]]:
        """递归返回嵌套树形结构

        :param root_id: 为 None 时返回所有根级群组，否则从指定群组开始
        :param include_kbs: 是否在每个群组节点上附加知识库列表
        """
        if root_id:
            root = await self.get_by_id(root_id, tenant_id)
            roots = [root] if root else []
        else:
            roots, _ = await self.list_roots(tenant_id, page_size=10000)

        async def _build_node(group: KnowledgeGroupModel) -> dict[str, Any]:
            node = group.to_dict()
            children = await self.list_children(group.id, tenant_id)
            node["children"] = [await _build_node(c) for c in children]
            if include_kbs:
                kb_svc = KnowledgeGroupKBService(self.session)
                kbs, kb_total = await kb_svc.list_kbs_in_group(
                    group.id, tenant_id, page=1, page_size=1000
                )
                node["knowledge_bases"] = [kb.to_dict() for kb in kbs]
                node["kb_count"] = kb_total
            return node

        return [await _build_node(r) for r in roots]

    async def update(
        self, group_id: str, tenant_id: str | None, name: str | None = None, description: str | None = None, ) -> KnowledgeGroupModel:
        """更新群组名称/描述"""
        group = await self.get_by_id(group_id, tenant_id)
        if not group:
            raise NotFoundException("KnowledgeGroup", group_id)
        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        group.update_time = now_timestamp()
        await self.session.flush()
        logger.info(f"Updated knowledge group: {group_id}")
        return group

    async def delete(
        self, group_id: str, tenant_id: str | None, user_id: str | None = None, ) -> bool:
        """删除群组（软删除）

        前置条件：无子群组且无关联知识库
        权限规则：user_id 不为空时展示 owner 才能删除
        """
        # 获取群组并验证租户权限
        group = await self.get_by_id_with_validation(group_id, tenant_id)

        if user_id:
            role = await self.get_user_role(group_id, user_id)
            if role != "owner":
                raise ValidationException(
                    f"Only the owner can delete group '{group_id}'"
                )

        # 检查子群组
        children = await self.list_children(group_id, tenant_id)
        if children:
            raise ValidationException(
                f"Cannot delete group '{group_id}' with {len(children)} child group(s). "
                "Please delete or move child groups first."
            )

        # 检查关联知识库
        kb_count_stmt = select(func.count()).where(
            KnowledgeBaseModel.group_id == group_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value, )
        kb_count = await self.session.scalar(kb_count_stmt) or 0
        if kb_count > 0:
            raise ValidationException(
                f"Cannot delete group '{group_id}' with {kb_count} knowledge base(s). "
                "Please remove or move knowledge bases first."
            )

        group.status = StatusEnum.DELETED.value
        group.update_time = now_timestamp()
        await self.session.commit()
        logger.info(f"Deleted knowledge group: {group_id} by user: {user_id or 'system'}")
        return True

    # ---------- 成员角色管理 ----------

    async def add_member(
        self, group_id: str, tenant_id: str | None, user_id: str, role: str = "member", ) -> KnowledgeGroupMemberModel:
        """添加或更新成员角色（UPSERT 语义）"""
        if role not in ROLE_HIERARCHY:
            raise ValidationException(f"Invalid role '{role}'. Must be one of: {list(ROLE_HIERARCHY.keys())}")

        stmt = select(KnowledgeGroupMemberModel).where(
            KnowledgeGroupMemberModel.group_id == group_id, KnowledgeGroupMemberModel.user_id == user_id, )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.role = role
            await self.session.flush()
            return existing

        member = KnowledgeGroupMemberModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("kgm"), tenant_id=tenant_id or DEFAULT_TENANT_ID, group_id=group_id, user_id=user_id, role=role, )
        self.session.add(member)
        await self.session.flush()
        logger.info(f"Added member {user_id} to group {group_id} with role {role}")
        return member

    async def remove_member(
        self, group_id: str, user_id: str, ) -> bool:
        """移除成员"""
        stmt = delete(KnowledgeGroupMemberModel).where(
            KnowledgeGroupMemberModel.group_id == group_id, KnowledgeGroupMemberModel.user_id == user_id, )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def list_members(
        self, group_id: str, ) -> list[KnowledgeGroupMemberModel]:
        """列出群组成员"""
        stmt = select(KnowledgeGroupMemberModel).where(
            KnowledgeGroupMemberModel.group_id == group_id, ).order_by(KnowledgeGroupMemberModel.create_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_role(
        self, group_id: str, user_id: str, ) -> str | None:
        """获取用户在指定群组中的角色"""
        stmt = select(KnowledgeGroupMemberModel.role).where(
            KnowledgeGroupMemberModel.group_id == group_id, KnowledgeGroupMemberModel.user_id == user_id, )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def check_permission(
        self, group_id: str, user_id: str, required_role: str, ) -> bool:
        """权限检测（支持角色继承：owner > admin > member > viewer）

        :return: True 表示有权限，False 表示无权限
        """
        user_role = await self.get_user_role(group_id, user_id)
        if not user_role:
            return False
        required_level = ROLE_HIERARCHY.get(required_role, 0)
        user_level = ROLE_HIERARCHY.get(user_role, 0)
        return user_level >= required_level

class KnowledgeGroupKBService:
    """知识库与群组的关联管理"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def attach_kb(
        self, kb_id: str, group_id: str, tenant_id: str | None, ) -> KnowledgeBaseModel:
        """将已有知识库关联到群组"""
        stmt = select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == kb_id, KnowledgeBaseModel.tenant_id == tenant_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value, )
        result = await self.session.execute(stmt)
        kb = result.scalar_one_or_none()
        if not kb:
            raise NotFoundException("KnowledgeBase", kb_id)

        kb.group_id = group_id
        kb.update_time = now_timestamp()
        await self.session.flush()
        logger.info(f"Attached kb {kb_id} to group {group_id}")
        return kb

    async def detach_kb(
        self, kb_id: str, tenant_id: str | None, ) -> KnowledgeBaseModel:
        """将知识库从群组中移除（group_id 设为 NULL）"""
        stmt = select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == kb_id, KnowledgeBaseModel.tenant_id == tenant_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value, )
        result = await self.session.execute(stmt)
        kb = result.scalar_one_or_none()
        if not kb:
            raise NotFoundException("KnowledgeBase", kb_id)

        kb.group_id = None
        kb.update_time = now_timestamp()
        await self.session.flush()
        logger.info(f"Detached kb {kb_id} from group")
        return kb

    async def list_kbs_in_group(
        self, group_id: str, tenant_id: str | None, page: int = 1, page_size: int = 20, name: str | None = None, ) -> tuple[list[KnowledgeBaseModel], int]:
        """列出群组内知识库"""
        stmt = select(KnowledgeBaseModel).where(
            KnowledgeBaseModel.group_id == group_id, KnowledgeBaseModel.tenant_id == tenant_id, KnowledgeBaseModel.status != StatusEnum.DELETED.value, )
        if name:
            stmt = stmt.where(KnowledgeBaseModel.name.like(f"%{name}%"))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(KnowledgeBaseModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

# ============== 用户权限组服务 ==============

# 授权目标类型常量
TARGET_TYPE_KB = "kb"
TARGET_TYPE_KB_GROUP = "kb_group"
# 主体类型常量
SUBJECT_TYPE_USER = "user"
SUBJECT_TYPE_PERM_GROUP = "perm_group"

class UserPermGroupService:
    """用户权限组服务 - 独立于知识库群组，仅用于批量授权"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 权限组 CRUD ----------

    async def create(
        self, tenant_id: str | None, name: str, description: str | None = None, created_by: str | None = None, ) -> UserPermissionGroupModel:
        """创建用户权限组"""
        pg = UserPermissionGroupModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("upg"), tenant_id=tenant_id or DEFAULT_TENANT_ID, name=name, description=description, status=StatusEnum.ACTIVE.value, created_by=created_by, )
        self.session.add(pg)
        await self.session.flush()
        logger.info(f"Created user permission group: {pg.id}, name: {name}")
        return pg

    async def get_by_id(
        self, perm_group_id: str, tenant_id: str | None, ) -> UserPermissionGroupModel | None:
        """获取用户权限组详情"""
        stmt = select(UserPermissionGroupModel).where(
            UserPermissionGroupModel.id == perm_group_id, UserPermissionGroupModel.tenant_id == tenant_id, UserPermissionGroupModel.status != StatusEnum.DELETED.value, )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self, tenant_id: str | None, name: str | None = None, page: int = 1, page_size: int = 20, ) -> tuple[list[UserPermissionGroupModel], int]:
        """列出用户权限组"""
        stmt = select(UserPermissionGroupModel).where(
            UserPermissionGroupModel.tenant_id == tenant_id, UserPermissionGroupModel.status != StatusEnum.DELETED.value, )
        if name:
            stmt = stmt.where(UserPermissionGroupModel.name.like(f"%{name}%"))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(UserPermissionGroupModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self, perm_group_id: str, tenant_id: str | None, name: str | None = None, description: str | None = None, ) -> UserPermissionGroupModel:
        """更新用户权限组"""
        pg = await self.get_by_id(perm_group_id, tenant_id)
        if not pg:
            raise NotFoundException("UserPermissionGroup", perm_group_id)
        if name is not None:
            pg.name = name
        if description is not None:
            pg.description = description
        pg.update_time = now_timestamp()
        await self.session.flush()
        return pg

    async def delete(
        self, perm_group_id: str, tenant_id: str | None, ) -> bool:
        """删除用户权限组（软删除，并清除关联授权和成员）"""
        pg = await self.get_by_id(perm_group_id, tenant_id)
        if not pg:
            raise NotFoundException("UserPermissionGroup", perm_group_id)

        # 删除成员
        await self.session.execute(
            delete(UserPermissionGroupMemberModel).where(
                UserPermissionGroupMemberModel.perm_group_id == perm_group_id
            )
        )
        # 删除关联的授权记录
        await self.session.execute(
            delete(KBPermissionGrantModel).where(
                KBPermissionGrantModel.subject_type == SUBJECT_TYPE_PERM_GROUP, KBPermissionGrantModel.subject_id == perm_group_id, )
        )
        pg.status = StatusEnum.DELETED.value
        pg.update_time = now_timestamp()
        await self.session.flush()
        logger.info(f"Deleted user permission group: {perm_group_id}")
        return True

    # ---------- 权限组成员管理 ----------

    async def add_member(
        self, perm_group_id: str, tenant_id: str | None, user_id: str, ) -> UserPermissionGroupMemberModel:
        """向权限组添加用户（已存在则忽略）"""
        stmt = select(UserPermissionGroupMemberModel).where(
            UserPermissionGroupMemberModel.perm_group_id == perm_group_id, UserPermissionGroupMemberModel.user_id == user_id, )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        member = UserPermissionGroupMemberModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("upgm"), tenant_id=tenant_id or DEFAULT_TENANT_ID, perm_group_id=perm_group_id, user_id=user_id, )
        self.session.add(member)
        await self.session.flush()
        logger.info(f"Added user {user_id} to perm group {perm_group_id}")
        return member

    async def remove_member(
        self, perm_group_id: str, user_id: str, ) -> bool:
        """从权限组移除用户"""
        result = await self.session.execute(
            delete(UserPermissionGroupMemberModel).where(
                UserPermissionGroupMemberModel.perm_group_id == perm_group_id, UserPermissionGroupMemberModel.user_id == user_id, )
        )
        await self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def list_members(
        self, perm_group_id: str, ) -> list[UserPermissionGroupMemberModel]:
        """列出权限组成员"""
        stmt = select(UserPermissionGroupMemberModel).where(
            UserPermissionGroupMemberModel.perm_group_id == perm_group_id, ).order_by(UserPermissionGroupMemberModel.create_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_user_perm_groups(
        self, tenant_id: str | None, user_id: str, ) -> list[UserPermissionGroupModel]:
        """查询用户所属的所有权限组"""
        subq = select(UserPermissionGroupMemberModel.perm_group_id).where(
            UserPermissionGroupMemberModel.user_id == user_id, )
        stmt = select(UserPermissionGroupModel).where(
            UserPermissionGroupModel.tenant_id == tenant_id, UserPermissionGroupModel.status != StatusEnum.DELETED.value, UserPermissionGroupModel.id.in_(subq), )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

class KBPermGrantService:
    """知识库权限授授服务

    支持授权主体：user 或 perm_group
    支持授权目标：kb（单个知识库）或 kb_group（知识库群组）
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def grant(
        self, tenant_id: str | None, subject_type: str, subject_id: str, target_type: str, target_id: str, role: str, created_by: str | None = None, ) -> KBPermissionGrantModel:
        """授权或更新权限（UPSERT 语义）"""
        if subject_type not in (SUBJECT_TYPE_USER, SUBJECT_TYPE_PERM_GROUP):
            raise ValidationException(f"Invalid subject_type: {subject_type}")
        if target_type not in (TARGET_TYPE_KB, TARGET_TYPE_KB_GROUP):
            raise ValidationException(f"Invalid target_type: {target_type}")
        if role not in ROLE_HIERARCHY:
            raise ValidationException(f"Invalid role: {role}")

        stmt = select(KBPermissionGrantModel).where(
            KBPermissionGrantModel.subject_type == subject_type, KBPermissionGrantModel.subject_id == subject_id, KBPermissionGrantModel.target_type == target_type, KBPermissionGrantModel.target_id == target_id, )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.role = role
            existing.update_time = now_timestamp()
            await self.session.flush()
            return existing

        grant = KBPermissionGrantModel(  # pyright: ignore[reportCallIssue]
            id=generate_id("kbg"), tenant_id=tenant_id or DEFAULT_TENANT_ID, subject_type=subject_type, subject_id=subject_id, target_type=target_type, target_id=target_id, role=role, created_by=created_by, )
        self.session.add(grant)
        await self.session.flush()
        logger.info(
            f"Granted {subject_type}:{subject_id} -> {target_type}:{target_id} role={role}"
        )
        return grant

    async def revoke(
        self, subject_type: str, subject_id: str, target_type: str, target_id: str, ) -> bool:
        """撒销授权"""
        result = await self.session.execute(
            delete(KBPermissionGrantModel).where(
                KBPermissionGrantModel.subject_type == subject_type, KBPermissionGrantModel.subject_id == subject_id, KBPermissionGrantModel.target_type == target_type, KBPermissionGrantModel.target_id == target_id, )
        )
        await self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def list_grants_on_target(
        self, target_type: str, target_id: str, tenant_id: str | None = None, ) -> list[KBPermissionGrantModel]:
        """查询某个目标的所有授权"""
        stmt = select(KBPermissionGrantModel).where(
            KBPermissionGrantModel.target_type == target_type, KBPermissionGrantModel.target_id == target_id, )
        if tenant_id:
            stmt = stmt.where(KBPermissionGrantModel.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_grants_by_subject(
        self, subject_type: str, subject_id: str, tenant_id: str | None = None, ) -> list[KBPermissionGrantModel]:
        """查询某个主体拥有的所有授权"""
        stmt = select(KBPermissionGrantModel).where(
            KBPermissionGrantModel.subject_type == subject_type, KBPermissionGrantModel.subject_id == subject_id, )
        if tenant_id:
            stmt = stmt.where(KBPermissionGrantModel.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_effective_role(
        self, user_id: str, target_type: str, target_id: str, tenant_id: str | None, ) -> str | None:
        """获取用户对指定目标的有效角色（取直接授权 + 权限组授权的最高级别）"""
        best_level = 0
        best_role: str | None = None

        # 1. 直接对用户的授权
        stmt = select(KBPermissionGrantModel.role).where(
            KBPermissionGrantModel.subject_type == SUBJECT_TYPE_USER, KBPermissionGrantModel.subject_id == user_id, KBPermissionGrantModel.target_type == target_type, KBPermissionGrantModel.target_id == target_id, )
        result = await self.session.execute(stmt)
        direct_role = result.scalar_one_or_none()
        if direct_role:
            level = ROLE_HIERARCHY.get(direct_role, 0)
            if level > best_level:
                best_level = level
                best_role = direct_role

        # 2. 通过用户权限组的授权
        # 先找到用户所属的权限组
        pg_subq = select(UserPermissionGroupMemberModel.perm_group_id).where(
            UserPermissionGroupMemberModel.user_id == user_id, )
        stmt2 = select(KBPermissionGrantModel.role).where(
            KBPermissionGrantModel.subject_type == SUBJECT_TYPE_PERM_GROUP, KBPermissionGrantModel.subject_id.in_(pg_subq), KBPermissionGrantModel.target_type == target_type, KBPermissionGrantModel.target_id == target_id, )
        result2 = await self.session.execute(stmt2)
        for row in result2.scalars().all():
            level = ROLE_HIERARCHY.get(row, 0)
            if level > best_level:
                best_level = level
                best_role = row

        return best_role

    async def check_user_permission(
        self, user_id: str, target_type: str, target_id: str, tenant_id: str | None, required_role: str, ) -> bool:
        """校验用户对目标是否有指定权限"""
        effective = await self.get_effective_role(
            user_id, target_type, target_id, tenant_id
        )
        if not effective:
            return False
        required_level = ROLE_HIERARCHY.get(required_role, 0)
        user_level = ROLE_HIERARCHY.get(effective, 0)
        return user_level >= required_level

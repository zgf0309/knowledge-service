# -*- coding: utf-8 -*-
"""
数据模型基类 - 参考 ragflow 的 Peewee ORM 设计
使用 SQLAlchemy 2.0 + Pydantic
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import String, Integer, BigInteger, Float, Text, JSON, DateTime, Boolean
from sqlalchemy.orm import declarative_base, declared_attr, Mapped, mapped_column
from sqlalchemy.dialects.mysql import LONGTEXT

Base = declarative_base()

class StatusEnum(str, Enum):
    """状态枚举"""
    ACTIVE = "1"
    INACTIVE = "0"
    DELETED = "2"

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class DocumentStatus(str, Enum):
    """文档状态"""
    PENDING = "pending"
    PARSING = "parsing"
    COMPLETED = "completed"
    FAILED = "failed"

class TimestampMixin:
    """时间戳混入类"""

    @declared_attr
    def create_time(cls) -> Mapped[int]:
        return mapped_column(BigInteger, default=lambda: int(datetime.now().timestamp() * 1000))  # type: ignore[return-type]

    @declared_attr
    def create_time_dt(cls) -> Mapped[datetime]:
        """数据库字段名：create_time_dt（对应 jusure_AI 的 create_date）"""
        return mapped_column(DateTime, default=datetime.utcnow)  # type: ignore[return-type]

    @declared_attr
    def update_time(cls) -> Mapped[int]:
        return mapped_column(BigInteger, default=lambda: int(datetime.now().timestamp() * 1000), onupdate=lambda: int(datetime.now().timestamp() * 1000))  # type: ignore[return-type]

    @declared_attr
    def update_time_dt(cls) -> Mapped[datetime]:
        """数据库字段名：update_time_dt（对应 jusure_AI 的 update_date）"""
        return mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # type: ignore[return-type]

class KnowledgeBaseModel(Base, TimestampMixin):
    """知识库模型 - 对应原 KnowledgeOrm"""
    __tablename__ = "knowledge_base"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID/组织 ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="知识库名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="知识库描述")
    language : Mapped[str] = mapped_column(String(32), default="Chinese", comment="语言")
    permission : Mapped[str] = mapped_column(String(16), default="me", comment="权限：me, team, public")
    
    embedding_model_id : Mapped[str | None] = mapped_column(String(128), nullable=True, comment="嵌入模型 ID")
    embedding_model_path : Mapped[str | None] = mapped_column(String(255), nullable=True, comment="嵌入模型路径")
    embedding_dims : Mapped[int] = mapped_column(Integer, default=1024, comment="向量维度")
    
    parser_id : Mapped[str] = mapped_column(String(32), default="naive", comment="解析器类型")
    parser_config : Mapped[Any] = mapped_column(JSON, default=dict, comment="解析配置")
    
    doc_num : Mapped[int] = mapped_column(Integer, default=0, comment="文档数量")
    token_num : Mapped[int] = mapped_column(BigInteger, default=0, comment="Token 数量")
    chunk_count : Mapped[int] = mapped_column(Integer, default=0, comment="切片数量")
    
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    
    graph_enabled : Mapped[int] = mapped_column(Integer, default=0, comment="是否启用知识图谱")
    graph_task_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="图谱任务 ID")
    
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者")
    group_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="所属群组 ID，NULL 表示未归属任何群组")
    
    def to_dict(self) -> dict[str, Any]:
        """返回与 jusure_AI 字段名对齐的字典"""
        # scope 映射：permission(ORM) → scope(对外)
        _perm_to_scope = {"team": 0, "me": 1}
        scope = _perm_to_scope.get(self.permission or "team", 0)
        return {
            "knowledge_id": self.id, "tenant_id": self.tenant_id, "knowledge_name": self.name, "knowledge_desc": self.description, "language": self.language, "scope": scope, "group_id": self.group_id, "status": self.status, "create_time": self.create_time, "create_date": self.create_time_dt, # 映射回 jusure_AI 的字段名
        }

class MediaDocumentModel(Base, TimestampMixin):
    """媒体文档模型 - 视频/音频文件元数据"""
    __tablename__ = "media_document"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    knowledge_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="所属知识库 ID")
    media_type : Mapped[str] = mapped_column(String(16), nullable=False, comment="媒体类型：video, audio")
    file_name : Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_url : Mapped[str] = mapped_column(String(512), nullable=False, comment="文件 URL")
    file_size : Mapped[int] = mapped_column(BigInteger, default=0, comment="文件大小 (字节)")
    file_suffix : Mapped[str] = mapped_column(String(16), nullable=False, comment="文件后缀")
    
    # 视频特有字段
    video_duration : Mapped[int] = mapped_column(BigInteger, default=0, comment="视频时长 (毫秒)")
    frame_rate : Mapped[float] = mapped_column(Float, default=0, comment="帧率")
    width : Mapped[int] = mapped_column(Integer, default=0, comment="宽度")
    height : Mapped[int] = mapped_column(Integer, default=0, comment="高度")
    key_frames : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="关键帧图片 URL 列表 (JSON)")
    
    # 音频特有字段
    audio_duration : Mapped[int] = mapped_column(BigInteger, default=0, comment="音频时长 (毫秒)")
    audio_format : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="音频格式")
    
    # 转录文本
    transcription_text : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="语音转写文本")
    transcription_status : Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING.value, comment="转录状态")
    
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "media_id": self.id, "knowledge_id": self.knowledge_id, "media_type": self.media_type, "file_name": self.file_name, "file_url": self.file_url, "file_size": self.file_size, "file_suffix": self.file_suffix, "video_duration": self.video_duration, "frame_rate": self.frame_rate, "width": self.width, "height": self.height, "key_frames": self.key_frames, "audio_duration": self.audio_duration, "audio_format": self.audio_format, "transcription_text": self.transcription_text, "transcription_status": self.transcription_status, "status": self.status, "create_time": self.create_time, "created_by": self.created_by, }

class MediaChunkModel(Base, TimestampMixin):
    """媒体切片模型 - 带时间戳的切片"""
    __tablename__ = "media_chunk"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    media_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="媒体文档 ID")
    knowledge_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库 ID")
    
    content : Mapped[str] = mapped_column(LONGTEXT, nullable=False, comment="切片内容")
    start_time : Mapped[int] = mapped_column(BigInteger, default=0, comment="开始时间 (毫秒)")
    end_time : Mapped[int] = mapped_column(BigInteger, default=0, comment="结束时间 (毫秒)")
    tokens : Mapped[int] = mapped_column(Integer, default=0, comment="Token 数")
    
    # 向量相关
    embedding_vector : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="向量数据")
    embedding_model_id : Mapped[str | None] = mapped_column(String(128), nullable=True, comment="嵌入模型 ID")
    
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "chunk_id": self.id, "media_id": self.media_id, "knowledge_id": self.knowledge_id, "content": self.content, "start_time": self.start_time, "end_time": self.end_time, "tokens": self.tokens, "embedding_vector": self.embedding_vector, "status": self.status, "create_time": self.create_time, }

class DocumentModel(Base, TimestampMixin):
    """文档模型 - 对应原 KnowledgeDocumentORM"""
    __tablename__ = "document"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    kb_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    
    name : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="文件名")
    type : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="文件类型")
    location : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="存储路径")
    size : Mapped[int] = mapped_column(BigInteger, default=0, comment="文件大小")
    
    parser_id : Mapped[str] = mapped_column(String(32), default="naive", comment="解析器类型")
    parser_config : Mapped[Any] = mapped_column(JSON, default=dict, comment="解析配置")
    
    chunk_count : Mapped[int] = mapped_column(Integer, default=0, comment="切片数量")
    token_num : Mapped[int] = mapped_column(BigInteger, default=0, comment="Token数量")
    
    progress : Mapped[float] = mapped_column(Float, default=0, comment="处理进度")
    progress_msg : Mapped[str] = mapped_column(Text, nullable=True, default="", comment="进度消息")
    
    status : Mapped[str] = mapped_column(String(16), default=DocumentStatus.PENDING.value, comment="状态")
    run : Mapped[str] = mapped_column(String(1), default="0", comment="运行状态: 0-停止, 1-运行")
    message : Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    
    content_hash : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="内容哈希")
    doc_metadata : Mapped[Any] = mapped_column(JSON, default=dict, comment="元数据")  # 改名避免与 SQLAlchemy 保留字冲突

    source_type : Mapped[str] = mapped_column(String(32), default="local", comment="来源类型")
    source_url : Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="来源URL")

    doc_category : Mapped[str] = mapped_column(String(32), default="text", index=True, comment="文档分类：text/table/web/image/audio")
    template_type : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="模板类型：legal/contract/resume/ppt/paper/qa")
    tags : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="自定义标签列表")

    def to_dict(self) -> dict[str, Any]:
        """返回与 jusure_AI 字段名对齐的字典"""
        return {
            "document_id": self.id, "knowledge_id": self.kb_id, "tenant_id": self.tenant_id, "doc_name": self.name, "doc_type": self.type, "location": self.location, "doc_size": self.size, "doc_category": self.doc_category, "template_type": self.template_type, "tags": self.tags, "parser_id": self.parser_id, "parser_config": self.parser_config, "chunk_count": self.chunk_count, "token_num": self.token_num, "progress": self.progress, "progress_msg": self.progress_msg, "status": self.status, "run": self.run, "content_hash": self.content_hash, "doc_metadata": self.doc_metadata, # 使用正确的字段名
            "source_type": self.source_type, "source_url": self.source_url, "create_time": self.create_time, "update_time": self.update_time
        }

class TaskModel(Base, TimestampMixin):
    """任务模型 - 参考 ragflow 的 Task 设计"""
    __tablename__ = "task"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    doc_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="文档ID")
    kb_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    
    task_type : Mapped[str] = mapped_column(String(32), default="parse", comment="任务类型: parse, embedding, graphrag, raptor")
    
    from_page : Mapped[int] = mapped_column(Integer, default=0, comment="起始页")
    to_page : Mapped[int] = mapped_column(Integer, default=100000000, comment="结束页")
    
    priority : Mapped[int] = mapped_column(Integer, default=0, comment="优先级")
    progress : Mapped[float] = mapped_column(Float, default=0, comment="进度")
    progress_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="进度消息")
    
    status : Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING.value, comment="状态")
    retry_count : Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    
    digest : Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    chunk_ids : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="切片ID列表(JSON)")
    
    result : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="执行结果")
    error_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "doc_id": self.doc_id, "kb_id": self.kb_id, "tenant_id": self.tenant_id, "task_type": self.task_type, "from_page": self.from_page, "to_page": self.to_page, "priority": self.priority, "progress": self.progress, "progress_msg": self.progress_msg, "status": self.status, "retry_count": self.retry_count, "digest": self.digest, "chunk_ids": self.chunk_ids, "result": self.result, "error_msg": self.error_msg, "create_time": self.create_time, "update_time": self.update_time
        }

class ChunkType(str, Enum):
    """切片类型枚举"""
    ORIGINAL = "original"  # 原文切片（自动生成）
    CUSTOM = "custom"      # 自定义切片（用户手动创建）

class ChunkModel(Base, TimestampMixin):
    """文档切片模型"""
    __tablename__ = "chunk"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    doc_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="文档 ID")
    kb_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库 ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    
    content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="切片内容")
    content_with_weight : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="带权重的完整内容（用于 big chunk 场景）")
    
    vector : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="向量 (JSON)")
    vector_dim : Mapped[int] = mapped_column(Integer, default=0, comment="向量维度")
    
    token_num : Mapped[int] = mapped_column(Integer, default=0, comment="Token 数量")
        
    chunk_metadata : Mapped[Any] = mapped_column(JSON, default=dict, comment="元数据")  # 改名避免与 SQLAlchemy 保留字冲突
        
    page_num : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页码")
    position : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="位置信息")
    
    important_keywords : Mapped[Any] = mapped_column(JSON, default=list, comment="重要关键词列表（兼容字段）")
    keyword_explanations : Mapped[Any] = mapped_column(JSON, default=dict, comment="关键词解释字典（兼容字段）")
    knowledge_points : Mapped[Any] = mapped_column(JSON, default=list, comment="知识点列表 [{id, content}]")
    
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    chunk_type : Mapped[str] = mapped_column(String(16), default=ChunkType.ORIGINAL.value, comment="切片类型: original=原文切片, custom=自定义切片")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "doc_id": self.doc_id, "kb_id": self.kb_id, "tenant_id": self.tenant_id, "content": self.content, "content_with_weight": self.content_with_weight, "token_num": self.token_num, "chunk_metadata": self.chunk_metadata, # 使用正确的字段名
            "page_num": self.page_num, "position": self.position, "important_keywords": self.important_keywords, "keyword_explanations": self.keyword_explanations, "knowledge_points": self.knowledge_points or [], "status": self.status, "chunk_type": self.chunk_type, # 切片类型
            "create_time": self.create_time, "update_time": self.update_time
        }

# ============== Pydantic Schemas ==============

class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求（字段名与 jusure_AI 对齐）"""
    knowledge_name: str = Field(..., min_length=1, max_length=255, description="知识库名称")
    knowledge_desc: str | None = Field(None, max_length=2000, description="知识库描述")
    language: str = Field(default="Chinese")
    scope: int = Field(default=0, description="权限类型: 0=公共(team), 1=个人(me), 2=私有(me)")
    aigc_model_id: str | None = Field(None, description="嵌入模型ID，对应 embedding_model_id")
    parser_id: str = Field(default="naive")
    parser_config: dict[str, Any] = Field(default_factory=dict)
    graph_enable: int = Field(default=0, description="是否启用知识图谱，对应 graph_enabled")
    group_id: str | None = Field(None, description="所属群组ID，NULL表示未归属任何群组")

class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求（字段名与 jusure_AI 对齐）"""
    knowledge_name: str | None = Field(None, min_length=1, max_length=255)
    knowledge_desc: str | None = None
    scope: int | None = Field(None, description="权限类型: 0=公共, 1=个人, 2=私有")
    parser_config: dict[str, Any] | None = None
    graph_enable: int | None = None
    status: int | None = Field(None, description="状态: 0=禁用, 1=启用")
    group_id: str | None = Field(None, description="所属群组ID，NULL表示未归属任何群组")

class KnowledgeBaseResponse(BaseModel):
    """知识库响应（字段名与 jusure_AI 对齐）"""
    knowledge_id: str = Field(description="知识库ID")
    tenant_id: str
    knowledge_name: str
    knowledge_desc: str | None
    language: str
    scope: int = Field(description="权限类型: 0=公共, 1=个人, 2=私有")
    group_id: str | None = Field(None, description="所属群组ID")
    aigc_model_id: str | None
    embedding_dims: int
    parser_id: str
    doc_num: int
    token_num: int
    chunk_count: int
    status: str
    graph_enable: int
    created_by: str | None
    create_time: int
    update_time: int

    class Config:
        from_attributes = True

class DocumentItem(BaseModel):
    """doc_list 中单个文档项（与 jusure_AI doc_list 元素结构对齐）"""
    doc_name: str
    doc_type: str
    doc_url: str
    doc_size: int = 0
    doc_id: str | None = None

class DocumentCreate(BaseModel):
    """创建文档请求（内部使用，ORM层）"""
    kb_id: str
    name: str
    type: str
    size: int = 0
    location: str | None = None
    parser_id: str = Field(default="naive")
    parser_config: dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(default="local")
    source_url: str | None = None

class DocumentResponse(BaseModel):
    """文档响应（字段名与 jusure_AI 对齐）"""
    document_id: str = Field(description="文档ID")
    knowledge_id: str = Field(description="知识库ID")
    tenant_id: str
    doc_name: str = Field(description="文档名称")
    doc_type: str = Field(description="文档类型")
    doc_size: int
    parser_id: str
    chunk_count: int
    token_num: int
    progress: float
    progress_msg: str
    status: str
    run: str
    content_hash: str | None
    source_type: str
    create_time: int
    update_time: int

    class Config:
        from_attributes = True

class TaskCreate(BaseModel):
    """创建任务请求"""
    doc_id: str
    kb_id: str
    task_type: str = Field(default="parse")
    from_page: int = Field(default=0)
    to_page: int = Field(default=100000000)
    priority: int = Field(default=0)

class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    doc_id: str
    kb_id: str
    tenant_id: str
    task_type: str
    from_page: int
    to_page: int
    priority: int
    progress: float
    progress_msg: str | None
    status: str
    retry_count: int
    error_msg: str | None
    create_time: int
    update_time: int

    class Config:
        from_attributes = True

# ============== 精细化文档导入 Schema ==============

class TextDocParseOptions(BaseModel):
    """文本文档解析选项"""
    layout_analysis: bool = Field(default=False, description="是否进行版面分析")
    image_ocr: bool = Field(default=False, description="对图片进行 OCR")
    multimodal_understanding: bool = Field(default=False, description="调用多模态大模型进行图片内容理解")
    chart_recognition: bool = Field(default=False, description="识别折线图、直方图等可视化图表")
    formula_recognition: bool = Field(default=False, description="识别文件中的公式内容")
    knowledge_enhancement: bool = Field(default=False, description="知识增强：调用大模型抽取更丰富的知识点")
    knowledge_graph_extraction: bool = Field(default=False, description="知识图谱提取")
    chunk_strategy: str = Field(default="default", description="切片策略：default/custom/whole/page")
    chunk_size: int | None = Field(default=None, description="自定义切片长度")
    chunk_regex: str | None = Field(default=None, description="自定义切分正则表达式")
    associate_filename: bool = Field(default=True, description="切片是否关联文件名")

class TableDocParseOptions(BaseModel):
    """表格型文档解析选项"""
    # 当前版本由 task_executor 使用默认表格读取工具，预留扩展字段
    pass

class WebDocParseOptions(BaseModel):
    """网页数据解析选项"""
    urls: list[str] = Field(..., min_length=1, description="一个或多个 URL")
    css_selector: str | None = Field(default=None, description="CSS 选择器筛选 HTML 内容")
    extract_links: bool = Field(default=False, description="是否抽取文本与图片的超链接")

class ImageDocParseOptions(BaseModel):
    """图片解析选项"""
    parse_mode: str = Field(default="auto", description="manual/auto/ocr")
    manual_description: str | None = Field(default=None, description="手动解析时的图片内容说明")
    image_ocr: bool = Field(default=False, description="是否启用 OCR 识别")

class AudioDocParseOptions(BaseModel):
    """音频解析选项"""
    knowledge_enhancement: bool = Field(default=False, description="是否进行知识增强")
    enhancement_types: list[str] = Field(default_factory=list, description="增强方式：question_gen/summary/triple_extraction")
    knowledge_graph_extraction: bool = Field(default=False, description="知识图谱提取")

class DocumentImportItem(BaseModel):
    """单个精细化导入文档项"""
    doc_category: str = Field(default="text", description="文档分类：text/table/web/image/audio")
    name: str = Field(..., min_length=1, description="文档名称")
    location: str | None = Field(default=None, description="文件存储路径（web 类型可空）")
    source_url: str | None = Field(default=None, description="网页/远程来源 URL")
    size: int = Field(default=0, description="文件大小")
    tags: list[str] = Field(default_factory=list, description="自定义标签列表")
    parse_options: dict[str, Any] = Field(default_factory=dict, description="对应类型的解析参数")

class TemplateDocumentImportItem(BaseModel):
    """单个模板导入文档项"""
    template_type: str = Field(..., description="模板类型：legal/contract/resume/ppt/paper/qa")
    name: str = Field(..., min_length=1, description="文档名称")
    location: str = Field(..., description="文件存储路径")
    size: int = Field(default=0, description="文件大小")
    tags: list[str] = Field(default_factory=list, description="自定义标签列表")
    parse_options: dict[str, Any] = Field(default_factory=dict, description="模板解析参数")

class TemplateDocumentImportRequest(BaseModel):
    """模板文档导入请求"""
    knowledge_id: str = Field(..., min_length=1, description="知识库 ID")
    documents: list[TemplateDocumentImportItem] = Field(..., min_length=1, description="文档列表")

class DocumentImportRequest(BaseModel):
    """精细化文档导入请求"""
    knowledge_id: str = Field(..., min_length=1, description="知识库 ID")
    documents: list[DocumentImportItem] = Field(..., min_length=1, description="文档列表")

# ============== AI 模型配置 ORM ==============

class AIModelModel(Base, TimestampMixin):
    """AI 模型配置 - 对应 jusure_AI 模型管理"""
    __tablename__ = "ai_model"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str] = mapped_column(String(128), nullable=False, comment="模型显示名称")
    model_type : Mapped[str] = mapped_column(String(32), default="chat", comment="模型类型: chat/embedding/rerank/tts/asr/image")
    provider : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="提供商: openai/qwen/ollama/...")
    model_name : Mapped[str] = mapped_column(String(128), nullable=False, comment="模型标识符")
    api_key : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="API Key（加密存储）")
    base_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="API Base URL")
    max_tokens : Mapped[int] = mapped_column(Integer, default=4096, comment="最大 token 数")
    temperature : Mapped[float] = mapped_column(Float, default=0.1, comment="温度")
    extra_params : Mapped[Any] = mapped_column(JSON, default=dict, comment="额外参数")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.id, "tenant_id": self.tenant_id, "name": self.name, "model_type": self.model_type, "provider": self.provider, "model_name": self.model_name, "base_url": self.base_url, "max_tokens": self.max_tokens, "temperature": self.temperature, "extra_params": self.extra_params, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 应用配置 ORM ==============

class AppModel(Base, TimestampMixin):
    """应用配置 - 对应 jusure_AI 的 AiApp"""
    __tablename__ = "app"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="应用名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="应用描述")
    icon : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标URL")
    app_type : Mapped[str] = mapped_column(String(32), default="chat", comment="应用类型: chat/flow/agent")

    # 模型配置
    model_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="关联AI模型ID")
    temperature : Mapped[float] = mapped_column(Float, default=0.1, comment="温度")
    max_tokens : Mapped[int] = mapped_column(Integer, default=4096, comment="最大token数")

    # 提示词
    system_prompt : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="系统提示词")
    prompt_template : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词模板")

    # 关联知识库（JSON 数组，存知识库ID列表）
    kb_ids : Mapped[Any] = mapped_column(JSON, default=list, comment="关联知识库ID列表")

    # RAG 配置
    top_k : Mapped[int] = mapped_column(Integer, default=5, comment="检索TopK")
    similarity_threshold : Mapped[float] = mapped_column(Float, default=0.2, comment="相似度阈值")
    rerank_enabled : Mapped[int] = mapped_column(Integer, default=0, comment="是否启用重排")
    rerank_model_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="重排模型ID")

    # 记忆与历史
    history_window : Mapped[int] = mapped_column(Integer, default=10, comment="历史对话轮数")
    memory_enabled : Mapped[int] = mapped_column(Integer, default=0, comment="是否启用记忆")

    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者")

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.id, "tenant_id": self.tenant_id, "name": self.name, "description": self.description, "icon": self.icon, "app_type": self.app_type, "model_id": self.model_id, "temperature": self.temperature, "max_tokens": self.max_tokens, "system_prompt": self.system_prompt, "prompt_template": self.prompt_template, "kb_ids": self.kb_ids, "top_k": self.top_k, "similarity_threshold": self.similarity_threshold, "rerank_enabled": self.rerank_enabled, "rerank_model_id": self.rerank_model_id, "history_window": self.history_window, "memory_enabled": self.memory_enabled, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 会话记录 ORM ==============

class SessionModel(Base, TimestampMixin):
    """会话记录 - 对应 jusure_AI 的 AppSession"""
    __tablename__ = "session"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    app_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="应用ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    user_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="用户ID")

    # 对话内容
    question : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="用户问题")
    answer : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="AI 回答")
    messages : Mapped[Any] = mapped_column(JSON, default=list, comment="完整消息列表")

    # 检索结果
    reference_chunks : Mapped[Any] = mapped_column(JSON, default=list, comment="引用切片列表")
    reference_docs : Mapped[Any] = mapped_column(JSON, default=list, comment="引用文档列表")

    # 推理配置快照
    model_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="使用的模型ID")
    prompt_tokens : Mapped[int] = mapped_column(Integer, default=0, comment="Prompt token 数")
    completion_tokens : Mapped[int] = mapped_column(Integer, default=0, comment="Completion token 数")

    # 反馈
    feedback : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="用户反馈: 1=好评/-1=差评")
    feedback_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="反馈内容")

    status : Mapped[str] = mapped_column(String(16), default="completed", comment="状态: running/completed/failed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.id, "app_id": self.app_id, "tenant_id": self.tenant_id, "user_id": self.user_id, "question": self.question, "answer": self.answer, "messages": self.messages, "reference_chunks": self.reference_chunks, "reference_docs": self.reference_docs, "model_id": self.model_id, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens, "feedback": self.feedback, "feedback_msg": self.feedback_msg, "status": self.status, "create_time": self.create_time, "update_time": self.update_time, }

# ============== Pydantic Schemas (新增) ==============

class AIModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    model_type: str = Field(default="chat")
    provider: str | None = None
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.1)
    extra_params: dict[str, Any] = Field(default_factory=dict)

class AIModelUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    extra_params: dict[str, Any] | None = None
    status: str | None = None

class AppCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon: str | None = None
    app_type: str = Field(default="chat")
    model_id: str | None = None
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=4096)
    system_prompt: str | None = None
    prompt_template: str | None = None
    kb_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5)
    similarity_threshold: float = Field(default=0.2)
    rerank_enabled: int = Field(default=0)
    rerank_model_id: str | None = None
    history_window: int = Field(default=10)
    memory_enabled: int = Field(default=0)

class AppUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    prompt_template: str | None = None
    kb_ids: list[str] | None = None
    top_k: int | None = None
    similarity_threshold: float | None = None
    rerank_enabled: int | None = None
    rerank_model_id: str | None = None
    history_window: int | None = None
    memory_enabled: int | None = None
    status: str | None = None

class SessionCreate(BaseModel):
    app_id: str
    user_id: str | None = None
    question: str
    messages: list[dict[str, Any]] = Field(default_factory=list)

# ============== 模型类型 ORM ==============

class AIModelTypeModel(Base, TimestampMixin):
    """AI 模型类型 - 对应 jusure_AI AigcModelType"""
    __tablename__ = "ai_model_type"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str] = mapped_column(String(128), nullable=False, comment="类型名称（aigc_type_name）")
    api_key : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="API Key")
    secret_key : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="Secret Key")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")

    def to_dict(self) -> dict[str, Any]:
        return {
            "aigc_type_id": self.id, "aigc_type_name": self.name, "api_key": self.api_key, "secret_key": self.secret_key, "status": self.status, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 提示词管理 ORM ==============

# 提示词类型/范围/模块映射（与 jusure_AI prompt_map 对齐）
PROMPT_TYPE_MAP = {
    1: "系统提示词", 2: "用户提示词", 3: "文档摘要提示词", 4: "标签提取提示词", 5: "实体提取提示词", 19: "QA对问答提示词", }

APPLY_RANGE_MAP = {
    1: "文档库", 2: "知识库", 3: "应用", 4: "会话", 5: "标签提取", 19: "QA对问答", }

APPLY_MODULE_MAP = {
    1: "文档库", 2: "应用", 3: "QA库", }

def map_int_label(mapping: dict[int, str], value: int | None) -> str:
    if value is None:
        return ""
    return mapping.get(value, "")

class PromptModel(Base, TimestampMixin):
    """提示词管理 - 对应 jusure_AI AigcPromptManagement"""
    __tablename__ = "prompt_management"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str | None] = mapped_column(String(255), nullable=True, comment="提示词名称（prompt_name）")
    desc : Mapped[str | None] = mapped_column(Text, nullable=True, comment="提示词描述（prompt_desc）")
    content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词内容（prompt_content）")
    prompt_txt : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词文本前端结构")
    prompt_type : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="提示词类型")
    apply_range : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用范围")
    apply_module : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用模块")
    is_default : Mapped[int] = mapped_column(Integer, default=0, comment="是否默认：0否 1是")
    is_private : Mapped[int] = mapped_column(Integer, default=0, comment="是否个人模板：0否 1是")
    params : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="提示词变量")
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态：0禁用 1启用")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者（tp_user_id）")

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.id, "prompt_name": self.name, "prompt_desc": self.desc, "prompt_content": self.content, "prompt_txt": self.prompt_txt, "prompt_type": self.prompt_type, "prompt_type_name": map_int_label(PROMPT_TYPE_MAP, self.prompt_type), "apply_range": self.apply_range, "apply_range_name": map_int_label(APPLY_RANGE_MAP, self.apply_range), "apply_module": self.apply_module, "apply_module_name": map_int_label(APPLY_MODULE_MAP, self.apply_module), "is_default": self.is_default, "is_private": self.is_private, "params": self.params, "status": self.status, "add_time": self.create_time, "update_time": self.update_time, }

class PromptHistoryModel(Base, TimestampMixin):
    """提示词历史记录 - 对应 jusure_AI AigcPromptHistoryManagement"""
    __tablename__ = "prompt_history"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    prompt_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="提示词ID")
    tp_user_id : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="操作用户ID")
    prompt_name : Mapped[str | None] = mapped_column(String(255), nullable=True, comment="提示词名称快照")
    prompt_desc : Mapped[str | None] = mapped_column(Text, nullable=True, comment="提示词描述快照")
    prompt_content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词内容快照")
    prompt_txt : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="前端结构快照")
    prompt_type : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="提示词类型快照")
    apply_range : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用范围快照")
    apply_module : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用模块快照")
    is_default : Mapped[int] = mapped_column(Integer, default=0, comment="是否默认快照")
    is_private : Mapped[int] = mapped_column(Integer, default=0, comment="是否个人快照")
    params : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="变量快照")
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态快照")

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_id": self.id, "tp_user_id": self.tp_user_id, "prompt_id": self.prompt_id, "prompt_type": self.prompt_type, "prompt_name": self.prompt_name, "prompt_desc": self.prompt_desc, "prompt_content": self.prompt_content, "prompt_txt": self.prompt_txt, "is_private": self.is_private, "status": self.status, "apply_range": self.apply_range, "apply_range_name": map_int_label(APPLY_RANGE_MAP, self.apply_range), "apply_module": self.apply_module, "apply_module_name": map_int_label(APPLY_MODULE_MAP, self.apply_module), "add_time": self.create_time, "update_time": self.update_time, }

# ============== 提示词模板 ORM ==============

class PromptTemplateModel(Base, TimestampMixin):
    """提示词模板 - 对应 jusure_AI AigcPromptTemplate"""
    __tablename__ = "prompt_template"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    prompt_type : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="提示词类型")
    apply_range : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用范围")
    apply_module : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="应用模块")
    params : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="提示词变量")
    prompt_txt : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词文本前端结构")
    content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词内容（prompt_content）")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")

    def to_dict(self) -> dict[str, Any]:
        return {
            "temp_id": self.id, "prompt_type": self.prompt_type, "prompt_type_name": map_int_label(PROMPT_TYPE_MAP, self.prompt_type), "apply_range": self.apply_range, "apply_range_name": map_int_label(APPLY_RANGE_MAP, self.apply_range), "apply_module": self.apply_module, "apply_module_name": map_int_label(APPLY_MODULE_MAP, self.apply_module), "params": self.params, "prompt_txt": self.prompt_txt, "prompt_content": self.content, "add_time": self.create_time, "update_time": self.update_time, }

# ============== 知识图谱 ORM ==============

class KnowledgeGraphModel(Base, TimestampMixin):
    """知识图谱 - 用于存储从文档中提取的知识图谱"""
    __tablename__ = "knowledge_graph"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="图谱名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="图谱描述")
    document_ids : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="关联文档 ID 列表")
    llm_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="使用的 LLM ID")
    entity_types : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="实体类型列表")
    graph_data : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="图数据 (JSON)")
    node_count : Mapped[int] = mapped_column(Integer, default=0, comment="节点数量")
    edge_count : Mapped[int] = mapped_column(Integer, default=0, comment="边数量")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.id, "graph_name": self.name, "description": self.description, "document_ids": self.document_ids, "llm_id": self.llm_id, "entity_types": self.entity_types, "node_count": self.node_count, "edge_count": self.edge_count, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 知识加工 ORM ==============

class ProcessServiceModel(Base, TimestampMixin):
    """知识加工服务 - 对应 jusure_AI AigcKnowledgeProcessSrv"""
    __tablename__ = "process_service"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="服务名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="服务描述")
    icon_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标URL")
    
    # 加工类型和方法
    process_srv_type : Mapped[str] = mapped_column(String(32), default="llm", comment="加工服务类型: llm=LLM加工, python=Python脚本, workflow=工作流")
    process_method : Mapped[str] = mapped_column(String(32), default="prompt", comment="加工方法: prompt=提示词, python=Python脚本, workflow=工作流")
    
    # 输入输出配置
    input_type : Mapped[str] = mapped_column(String(32), default="text", comment="输入类型: text=文本, file=文件, knowledge=知识库")
    input_prefix : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="输入前缀(逗号分隔)")
    output_type : Mapped[str] = mapped_column(String(32), default="text", comment="输出类型: text=文本, file=文件, knowledge=知识库")
    output_method : Mapped[str] = mapped_column(String(32), default="content", comment="输出方式: content=内容, file=文件, knowledge=知识库")
    output_prefix : Mapped[str | None] = mapped_column(Text, nullable=True, comment="输出前缀")
    output_knowledge_ids : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="输出知识库ID列表")
    
    # LLM 配置
    aigc_model_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="LLM模型ID")
    prompt : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="提示词模板")
    
    # Python 脚本配置
    script_array : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="脚本ID列表")
    
    # 工作流配置
    flow_array : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="工作流数组")
    
    # 状态
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态：0禁用 1启用")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "process_srv_id": self.id, "process_srv_name": self.name, "description": self.description, "icon_url": self.icon_url, "process_srv_type": self.process_srv_type, "process_method": self.process_method, "input_type": self.input_type, "input_prefix": self.input_prefix.split(', ') if self.input_prefix else [], "output_type": self.output_type, "output_method": self.output_method, "output_prefix": self.output_prefix, "output_knowledge_ids": self.output_knowledge_ids, "aigc_model_id": self.aigc_model_id, "prompt": self.prompt, "script_array": self.script_array, "flow_array": self.flow_array, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

class ProcessTaskModel(Base, TimestampMixin):
    """知识加工任务 - 对应 jusure_AI AigcKnowledgeProcessTask"""
    __tablename__ = "process_task"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    process_srv_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识加工服务ID")
    
    # 任务名称和描述
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="任务名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="任务描述")
    
    # 输入配置
    input_type : Mapped[str] = mapped_column(String(32), default="text", comment="输入类型: text=文本, file=文件, knowledge=知识库")
    input_text : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="输入文本")
    input_file_list : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="输入文件列表")
    input_knowledge_list : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="输入知识库列表")
    
    # 输出配置
    output_type : Mapped[str] = mapped_column(String(32), default="text", comment="输出类型: text=文本, file=文件, knowledge=知识库")
    output_content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="输出内容")
    output_file_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="输出文件URL")
    
    # 任务状态
    status : Mapped[str] = mapped_column(String(32), default="pending", comment="状态: pending/running/completed/failed/cancelled")
    progress : Mapped[float] = mapped_column(Float, default=0, comment="进度百分比")
    progress_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="进度消息")
    error_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    
    # 父任务
    parent_task_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="父任务ID")
    
    # 执行信息
    start_time : Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="开始时间戳")
    end_time : Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="结束时间戳")
    executed_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="执行者")
    
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.id, "process_srv_id": self.process_srv_id, "name": self.name, "description": self.description, "input_type": self.input_type, "input_text": self.input_text, "input_file_list": self.input_file_list, "input_knowledge_list": self.input_knowledge_list, "output_type": self.output_type, "output_content": self.output_content, "output_file_url": self.output_file_url, "status": self.status, "progress": self.progress, "progress_msg": self.progress_msg, "error_msg": self.error_msg, "parent_task_id": self.parent_task_id, "start_time": self.start_time, "end_time": self.end_time, "executed_by": self.executed_by, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

class PythonScriptModel(Base, TimestampMixin):
    """Python 脚本 - 对应 jusure_AI AigcPythonScript"""
    __tablename__ = "python_script"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="脚本名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="脚本描述")
    script_code : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="脚本代码")
    script_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="脚本文件URL")
    params_schema : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="参数JSON Schema")
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态：0禁用 1启用")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.id, "script_name": self.name, "description": self.description, "script_code": self.script_code, "script_url": self.script_url, "params_schema": self.params_schema, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 知识加工 Pydantic Schemas ==============

class ProcessServiceCreate(BaseModel):
    """创建知识加工服务"""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    icon_url: str | None = None
    process_srv_type: str = Field(default="llm")
    process_method: str = Field(default="prompt")
    input_type: str = Field(default="text")
    input_prefix: list[str] | None = None
    output_type: str = Field(default="text")
    output_method: str = Field(default="content")
    output_prefix: str | None = None
    output_knowledge_ids: list[str] | None = None
    aigc_model_id: str | None = None
    prompt: str | None = None
    script_array: list[str] | None = None
    flow_array: list[str] | None = None

class ProcessServiceUpdate(BaseModel):
    """更新知识加工服务"""
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None
    process_srv_type: str | None = None
    process_method: str | None = None
    input_type: str | None = None
    input_prefix: list[str] | None = None
    output_type: str | None = None
    output_method: str | None = None
    output_prefix: str | None = None
    output_knowledge_ids: list[str] | None = None
    aigc_model_id: str | None = None
    prompt: str | None = None
    script_array: list[str] | None = None
    flow_array: list[str] | None = None
    status: int | None = None

class ProcessTaskCreate(BaseModel):
    """创建知识加工任务"""
    process_srv_id: str
    name: str | None = None
    description: str | None = None
    input_type: str = Field(default="text")
    input_text: str | None = None
    input_file_list: list[dict[str, Any]] | None = None
    input_knowledge_list: list[dict[str, Any]] | None = None

class PythonScriptCreate(BaseModel):
    """创建 Python 脚本"""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    script_code: str | None = None
    script_url: str | None = None
    params_schema: dict[str, Any] | None = None

# ============== Agent/工作流 ORM ==============

class AgentModel(Base, TimestampMixin):
    """Agent/工作流应用 - 基于 Ragflow Canvas DSL"""
    __tablename__ = "agent_app"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="应用名称")
    desc : Mapped[str | None] = mapped_column(Text, nullable=True, comment="应用描述")
    icon_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标 URL")
    dsl : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="Canvas DSL 配置")
    welcome_content : Mapped[str | None] = mapped_column(Text, nullable=True, comment="欢迎语")
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态：0 禁用 1 启用")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.id, "app_name": self.name, "app_desc": self.desc, "icon_url": self.icon_url, "dsl": self.dsl, "welcome_content": self.welcome_content, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# ============== 记忆模块 ORM ==============

class MemoryModel(Base, TimestampMixin):
    """会话记忆 - 对应 jusure_AI AppSessionMemory"""
    __tablename__ = "memory"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    app_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="应用 ID")
    session_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="会话 ID")
    user_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="用户 ID")
    
    # 记忆内容
    memory_type : Mapped[str] = mapped_column(String(32), default="short", comment="记忆类型：short=短期，long=长期")
    content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="记忆内容")
    summary : Mapped[str | None] = mapped_column(Text, nullable=True, comment="记忆摘要")
    
    # 向量化
    embedding : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="向量 (JSON)")
    embedding_model_id : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="嵌入模型 ID")
    
    # 权重和重要性
    weight : Mapped[float] = mapped_column(Float, default=1.0, comment="记忆权重")
    importance : Mapped[float] = mapped_column(Float, default=0.5, comment="重要性评分")
    
    # 访问记录
    access_count : Mapped[int] = mapped_column(Integer, default=0, comment="访问次数")
    last_access_time : Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="最后访问时间")
    
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="创建者")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.id, "tenant_id": self.tenant_id, "app_id": self.app_id, "session_id": self.session_id, "user_id": self.user_id, "memory_type": self.memory_type, "content": self.content, "summary": self.summary, "embedding": self.embedding, "embedding_model_id": self.embedding_model_id, "weight": self.weight, "importance": self.importance, "access_count": self.access_count, "last_access_time": self.last_access_time, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

class MemoryCreate(BaseModel):
    """创建记忆"""
    app_id: str
    session_id: str | None = None
    user_id: str | None = None
    memory_type: str = Field(default="short")
    content: str
    summary: str | None = None
    importance: float = Field(default=0.5)

class MemoryUpdate(BaseModel):
    """更新记忆"""
    content: str | None = None
    summary: str | None = None
    weight: float | None = None
    importance: float | None = None

class QALibraryModel(Base, TimestampMixin):
    """QA 库模型"""
    __tablename__ = "qa_library"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    qa_name : Mapped[str] = mapped_column(String(255), nullable=False, comment="QA库名称")
    qa_desc : Mapped[str | None] = mapped_column(Text, nullable=True, comment="QA 库描述")
    aigc_model_id : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="AI 模型 ID")
    icon_url : Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标 URL")
    status : Mapped[int] = mapped_column(Integer, default=1, comment="状态：0-禁用，1-启用")
    
    item_count : Mapped[int] = mapped_column(Integer, default=0, comment="QA 条目数量")
    use_count : Mapped[int] = mapped_column(BigInteger, default=0, comment="使用次数")
    
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者 ID")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "qa_lib_id": self.id, "tenant_id": self.tenant_id, "qa_name": self.qa_name, "qa_desc": self.qa_desc, "aigc_model_id": self.aigc_model_id, "icon_url": self.icon_url, "status": self.status, "item_count": self.item_count, "use_count": self.use_count, "create_time": self.create_time, "update_time": self.update_time, }

class QAItemModel(Base, TimestampMixin):
    """QA 条目模型"""
    __tablename__ = "qa_item"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    qa_lib_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="QA 库 ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    
    question : Mapped[str] = mapped_column(Text, nullable=False, comment="问题")
    answer : Mapped[str] = mapped_column(Text, nullable=False, comment="答案")
    qa_modal : Mapped[int] = mapped_column(Integer, default=0, comment="QA 模式：0-普通，1-高级")
    
    tags : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="标签列表")
    similarity_questions : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="相似问题列表")
    
    use_count : Mapped[int] = mapped_column(BigInteger, default=0, comment="使用次数")
    feedback_score : Mapped[float] = mapped_column(Float, default=0, comment="平均评分")
    
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者 ID")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "qa_lib_id": self.qa_lib_id, "tenant_id": self.tenant_id, "question": self.question, "answer": self.answer, "qa_modal": self.qa_modal, "tags": self.tags or [], "similarity_questions": self.similarity_questions or [], "use_count": self.use_count, "feedback_score": self.feedback_score, "create_time": self.create_time, "update_time": self.update_time, }

class FeedbackModel(Base, TimestampMixin):
    """反馈模型"""
    __tablename__ = "feedback"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    session_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="会话 ID")
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    user_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="用户 ID")
    
    score : Mapped[int | None] = mapped_column(Integer, nullable=True, comment="评分：1-5")
    comment : Mapped[str | None] = mapped_column(Text, nullable=True, comment="评论内容")
    feedback_type : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="反馈类型：like/dislike")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "session_id": self.session_id, "tenant_id": self.tenant_id, "user_id": self.user_id, "score": self.score, "comment": self.comment, "feedback_type": self.feedback_type, "create_time": self.create_time, }

class DocumentCleanRule(Base, TimestampMixin):
    """文档清洗规则模型"""
    __tablename__ = "document_clean_rule"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    rule_name : Mapped[str] = mapped_column(String(255), nullable=False, comment="规则名称")
    rule_content : Mapped[str] = mapped_column(Text, nullable=False, comment="规则内容（提示词/脚本）")
    rule_desc : Mapped[str | None] = mapped_column(Text, nullable=True, comment="规则描述")
    rule_type : Mapped[int] = mapped_column(Integer, default=0, comment="规则类型：0-脚本处理，1-模型处理")
    doc_type : Mapped[int] = mapped_column(Integer, default=0, comment="适用文档类型：0-通用，1-文本，2-Excel, 3-QA")
    is_builtin : Mapped[int] = mapped_column(Integer, default=0, comment="是否内置：0-否，1-是")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者 ID")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.id, "tenant_id": self.tenant_id, "rule_name": self.rule_name, "rule_content": self.rule_content, "rule_desc": self.rule_desc, "rule_type": self.rule_type, "doc_type": self.doc_type, "is_builtin": self.is_builtin, "create_time": self.create_time, "update_time": self.update_time, }

class DocumentRuleRelation(Base, TimestampMixin):
    """文档清洗关联模型"""
    __tablename__ = "document_rule_relation"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    document_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="文档 ID")
    rule_id : Mapped[str] = mapped_column(String(32), nullable=False, comment="规则 ID")
    rule_type : Mapped[int] = mapped_column(Integer, default=0, comment="规则类型：0-脚本，1-模型")
    priority : Mapped[int] = mapped_column(Integer, default=0, comment="执行优先级")
    enabled : Mapped[int] = mapped_column(Integer, default=1, comment="是否启用：0-否，1-是")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.id, "tenant_id": self.tenant_id, "document_id": self.document_id, "rule_id": self.rule_id, "rule_type": self.rule_type, "priority": self.priority, "enabled": self.enabled, "create_time": self.create_time, }

class KnowledgeRulePreset(Base, TimestampMixin):
    """知识库清洗预配置模型"""
    __tablename__ = "knowledge_rule_preset"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    knowledge_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库 ID")
    rule_id : Mapped[str] = mapped_column(String(32), nullable=False, comment="规则 ID")
    rule_type : Mapped[int] = mapped_column(Integer, default=0, comment="规则类型：0-脚本，1-模型")
    enabled : Mapped[int] = mapped_column(Integer, default=1, comment="是否启用：0-否，1-是")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.id, "tenant_id": self.tenant_id, "knowledge_id": self.knowledge_id, "rule_id": self.rule_id, "rule_type": self.rule_type, "enabled": self.enabled, "create_time": self.create_time, }

class DocumentCleanTask(Base, TimestampMixin):
    """文档清洗任务模型"""
    __tablename__ = "document_clean_task"
    
    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    knowledge_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="知识库 ID")
    document_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="文档 ID")
    task_type : Mapped[str] = mapped_column(String(32), default="clean", comment="任务类型：clean-清洗，filter-过滤")
    
    state : Mapped[str] = mapped_column(String(16), default="pending", comment="状态：pending/running/completed/failed")
    progress : Mapped[float] = mapped_column(Float, default=0, comment="进度：0-100")
    progress_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="进度消息")
    
    original_url : Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="原始文档 URL")
    cleaned_url : Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="清洗后文档 URL")
    cleaned_content : Mapped[str | None] = mapped_column(LONGTEXT, nullable=True, comment="清洗后内容")
    statistics : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="统计信息")
    
    error_msg : Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    retry_count : Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    
    aigc_model_id : Mapped[str | None] = mapped_column(String(64), nullable=True, comment="使用的 AI 模型 ID")
    rules_applied : Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="应用的规则列表")
    
    start_time : Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="开始时间戳")
    end_time : Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="结束时间戳")
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.id, "tenant_id": self.tenant_id, "knowledge_id": self.knowledge_id, "document_id": self.document_id, "task_type": self.task_type, "state": self.state, "progress": self.progress, "progress_msg": self.progress_msg, "original_url": self.original_url, "cleaned_url": self.cleaned_url, "cleaned_content": self.cleaned_content, "statistics": self.statistics, "error_msg": self.error_msg, "aigc_model_id": self.aigc_model_id, "rules_applied": self.rules_applied, "create_time": self.create_time, "start_time": self.start_time, "end_time": self.end_time, }

# ============== 知识库群组 ORM ==============

class KnowledgeGroupModel(Base, TimestampMixin):
    """知识库群组 - 邻接表模型，支持无限层级的树形组织架构"""
    __tablename__ = "knowledge_group"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="群组名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="群组描述")
    parent_id : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="父群组 ID，NULL 表示根群组")
    path : Mapped[str] = mapped_column(String(1024), default="", comment="祖先路径：/root_id/parent_id/self_id/")
    depth : Mapped[int] = mapped_column(Integer, default=0, comment="层级深度，根节点为 0")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者")

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.id, "tenant_id": self.tenant_id, "name": self.name, "description": self.description, "parent_id": self.parent_id, "path": self.path, "depth": self.depth, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

class KnowledgeGroupMemberModel(Base):
    """知识库群组成员角色表"""
    __tablename__ = "knowledge_group_member"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    group_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="群组 ID")
    user_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="用户 ID")
    role : Mapped[str] = mapped_column(String(16), default="member", comment="角色：owner/admin/member/viewer")
    create_time : Mapped[int] = mapped_column(BigInteger, default=lambda: int(datetime.now().timestamp() * 1000))
    create_date : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tenant_id": self.tenant_id, "group_id": self.group_id, "user_id": self.user_id, "role": self.role, "create_time": self.create_time, }

# ============== 用户权限组 ORM ==============

class UserPermissionGroupModel(Base, TimestampMixin):
    """用户权限组 - 独立于知识库群组，仅用于批量授权"""
    __tablename__ = "user_permission_group"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    name : Mapped[str] = mapped_column(String(255), nullable=False, comment="权限组名称")
    description : Mapped[str | None] = mapped_column(Text, nullable=True, comment="权限组描述")
    status : Mapped[str] = mapped_column(String(1), default=StatusEnum.ACTIVE.value, comment="状态")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, index=True, comment="创建者")

    def to_dict(self) -> dict[str, Any]:
        return {
            "perm_group_id": self.id, "tenant_id": self.tenant_id, "name": self.name, "description": self.description, "status": self.status, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

class UserPermissionGroupMemberModel(Base):
    """用户权限组成员表"""
    __tablename__ = "user_permission_group_member"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")
    perm_group_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="权限组 ID")
    user_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="用户 ID")
    create_time : Mapped[int] = mapped_column(BigInteger, default=lambda: int(datetime.now().timestamp() * 1000))
    create_date : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tenant_id": self.tenant_id, "perm_group_id": self.perm_group_id, "user_id": self.user_id, "create_time": self.create_time, }

class KBPermissionGrantModel(Base, TimestampMixin):
    """知识库权限授权表

    subject_type: user | perm_group
    target_type:  kb   | kb_group
    role:         owner | admin | member | viewer
    """
    __tablename__ = "kb_permission_grant"

    id : Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tenant_id : Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="租户 ID")

    subject_type : Mapped[str] = mapped_column(String(16), nullable=False, comment="主体类型：user / perm_group")
    subject_id : Mapped[str] = mapped_column(String(32), nullable=False, comment="主体 ID")

    target_type : Mapped[str] = mapped_column(String(16), nullable=False, comment="目标类型：kb / kb_group")
    target_id : Mapped[str] = mapped_column(String(32), nullable=False, comment="目标 ID")

    role : Mapped[str] = mapped_column(String(16), nullable=False, default="viewer", comment="权限角色")
    created_by : Mapped[str | None] = mapped_column(String(32), nullable=True, comment="授权操作者")

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.id, "tenant_id": self.tenant_id, "subject_type": self.subject_type, "subject_id": self.subject_id, "target_type": self.target_type, "target_id": self.target_id, "role": self.role, "created_by": self.created_by, "create_time": self.create_time, "update_time": self.update_time, }

# -*- coding: utf-8 -*-
"""
微服务配置管理 - 参考 ragflow 的配置设计
支持环境变量驱动，配置与代码分离
"""
import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class ServiceConfig(BaseSettings):
    """服务配置"""
    service_name: str = Field(default="knowledge-service", validation_alias="SERVICE_NAME")
    host: str = Field(default="0.0.0.0", validation_alias="SERVICE_HOST")
    port: int = Field(default=7101, validation_alias="SERVICE_PORT")
    workers: int = Field(default=4, validation_alias="SERVICE_WORKERS")
    debug: bool = Field(default=False, validation_alias="DEBUG")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off", ""}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class MySQLConfig(BaseSettings):
    """MySQL 配置"""
    host: str = Field(default="localhost", validation_alias="MYSQL_HOST")
    port: int = Field(default=3306, validation_alias="MYSQL_PORT")
    user: str = Field(default="root", validation_alias="MYSQL_USER")
    password: str = Field(default="root123", validation_alias="MYSQL_PASSWORD")
    database: str = Field(default="galaxy_rag", validation_alias="MYSQL_DATABASE")
    max_connections: int = Field(default=100, validation_alias="MYSQL_MAX_CONNECTIONS")
    pool_size: int = Field(default=10, validation_alias="MYSQL_POOL_SIZE")
    
    @property
    def connection_url(self) -> str:
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class MongoDBConfig(BaseSettings):
    """MongoDB 配置"""
    host: str = Field(default="localhost", validation_alias="MONGO_HOST")
    port: int = Field(default=27017, validation_alias="MONGO_PORT")
    user: str = Field(default="", validation_alias="MONGO_USER")
    password: str = Field(default="", validation_alias="MONGO_PASSWORD")
    database: str = Field(default="jusure_ai", validation_alias="MONGO_DATABASE")
    
    @property
    def connection_url(self) -> str:
        if self.user and self.password:
            return f"mongodb://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        return f"mongodb://{self.host}:{self.port}/{self.database}"
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class RedisConfig(BaseSettings):
    """Redis 配置"""
    host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    port: int = Field(default=6379, validation_alias="REDIS_PORT")
    password: str = Field(default="", validation_alias="REDIS_PASSWORD")
    db: int = Field(default=0, validation_alias="REDIS_DB")
    
    @property
    def connection_url(self) -> str:
        if self.password:
            return f"redis://default:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class MinIOConfig(BaseSettings):
    """MinIO 配置"""
    host: str = Field(default="localhost", validation_alias="MINIO_HOST")
    port: int = Field(default=9000, validation_alias="MINIO_PORT")
    access_key: str = Field(default="minioadmin", validation_alias="MINIO_ACCESS_KEY")
    secret_key: str = Field(default="minioadmin", validation_alias="MINIO_SECRET_KEY")
    secure: bool = Field(default=False, validation_alias="MINIO_SECURE")
    bucket: str = Field(default="jusure", validation_alias="MINIO_BUCKET")
    
    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class ElasticsearchConfig(BaseSettings):
    """Elasticsearch 配置"""
    host: str = Field(default="localhost", validation_alias="ES_HOST")
    port: int = Field(default=9200, validation_alias="ES_PORT")
    user: str = Field(default="", validation_alias="ES_USER")
    password: str = Field(default="", validation_alias="ES_PASSWORD")
    scheme: str = Field(default="http", validation_alias="ES_SCHEME")
    
    @property
    def connection_url(self) -> str:
        if self.user and self.password:
            return f"{self.scheme}://{self.user}:{self.password}@{self.host}:{self.port}"
        return f"{self.scheme}://{self.host}:{self.port}"
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class VectorStoreConfig(BaseSettings):
    """向量存储配置"""
    store_type: str = Field(default="elasticsearch", validation_alias="VECTOR_STORE_TYPE")
    index_prefix: str = Field(default="jusure", validation_alias="VECTOR_INDEX_PREFIX")
    embedding_dims: int = Field(default=1024, validation_alias="EMBEDDING_DIMS")
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class LLMConfig(BaseSettings):
    """LLM 配置"""
    default_llm_factory: str = Field(default="openai", validation_alias="DEFAULT_LLM_FACTORY")
    default_llm_model: str = Field(default="gpt-4", validation_alias="DEFAULT_LLM_MODEL")
    default_embedding_model: str = Field(default="bge-m3", validation_alias="DEFAULT_EMBEDDING_MODEL")
    api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    base_url: str = Field(default="", validation_alias="LLM_BASE_URL")
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class ParserConfig(BaseSettings):
    """
    文档解析器配置
    - ragflow_mode: 启用后各格式解析器融合 ragflow 的解析逻辑
      PDF:   使用 ragflow PlainParser（纯文本流程，不依赖 OCR 模型）
      DOCX:  启用 ragflow 表格内容语义化（按数据类型决定序列化策略）
      HTML:  使用 ragflow RAGFlowHtmlParser（递归块解析 + 标题 Markdown 化）
      Markdown: 使用 ragflow MarkdownElementExtractor（代码块/列表/引用分块）
      Excel: 使用 ragflow RAGFlowExcelParser（多 Sheet、CSV 降级、HTML 输出）
      PPTX:  使用 ragflow RAGFlowPptParser（项目符号、表格、组合形状）
      TXT:   使用 ragflow RAGFlowTxtParser（自定义分隔符反引号语法）
    - chunk_token_num: 每个切片的最大 token 数
    - overlap_percent: 切片间重叠比例（0~100）
    - ragflow_pdf_plain: 是否使用 ragflow PlainParser（仅在 ragflow_mode=True 时有效）
      False: 使用 jusure_AI 三库联合方案（fitz+pdfplumber+pdfminer）
      True:  使用 ragflow PlainParser（基于 fitz，轻量但无表格识别）
    """
    ragflow_mode: bool = Field(default=False, validation_alias="PARSER_RAGFLOW_MODE")
    ragflow_pdf_plain: bool = Field(default=False, validation_alias="PARSER_RAGFLOW_PDF_PLAIN")
    chunk_token_num: int = Field(default=512, validation_alias="PARSER_CHUNK_TOKEN_NUM")
    overlap_percent: float = Field(default=0, validation_alias="PARSER_OVERLAP_PERCENT")
    delimiter: str = Field(default="\n!?。；！？", validation_alias="PARSER_DELIMITER")
    # PDF 专项
    pdf_header_footer_margin: int = Field(default=50, validation_alias="PARSER_PDF_MARGIN")
    pdf_image_area_thr: int = Field(default=10, validation_alias="PARSER_PDF_IMG_AREA_THR")
    # HTML 专项
    html_chunk_token_num: int = Field(default=512, validation_alias="PARSER_HTML_CHUNK_TOKEN_NUM")
    # Excel 专项
    excel_chunk_rows: int = Field(default=256, validation_alias="PARSER_EXCEL_CHUNK_ROWS")
    # 容器文件（ZIP/TAR）内子文档并发解析线程数
    # 0 或负数表示使用 min(CPU 核数，子文档数量)，不超过 32
    parse_workers: int = Field(default=4, validation_alias="PARSER_PARSE_WORKERS")
    # 容器文件中单个子文件的最大大小（MB），超出则跳过
    archive_max_file_mb: int = Field(default=50, validation_alias="PARSER_ARCHIVE_MAX_FILE_MB")
    # 分句配置（方案 C：SaT 神经网络分句）
    # use_sat=False 时降级为正则分句
    use_sat: bool = Field(default=True, validation_alias="PARSER_USE_SAT")
    sat_model: str = Field(default="sat-3l-sm", validation_alias="PARSER_SAT_MODEL")
    # 语义分块配置（方案 D：基于 embedding 相似度的语义边界检测）
    # 启用后先执行 SaT 分句，再按语义边界合并
    semantic_chunking: bool = Field(default=False, validation_alias="PARSER_SEMANTIC_CHUNKING")
    # 语义边界阈值（percentile/std_deviation 策略下的参考值）
    semantic_threshold: float = Field(default=0.5, validation_alias="PARSER_SEMANTIC_THRESHOLD")
    # 阈值策略：percentile / std_deviation / gradient
    semantic_breakpoint_type: str = Field(default="percentile", validation_alias="PARSER_SEMANTIC_BREAKPOINT_TYPE")
    # PageIndex 集成配置
    pageindex_auto_enabled: bool = Field(default=True, validation_alias="PAGEINDEX_AUTO_ENABLED")
    pageindex_min_pdf_pages: int = Field(default=5, validation_alias="PAGEINDEX_MIN_PDF_PAGES")
    pageindex_min_md_headings: int = Field(default=3, validation_alias="PAGEINDEX_MIN_MD_HEADINGS")
    pageindex_service_url: str = Field(default="http://localhost:7115", validation_alias="PAGEINDEX_SERVICE_URL")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class TaskExecutorConfig(BaseSettings):
    """任务执行器配置"""
    max_concurrent_tasks: int = Field(default=5, validation_alias="MAX_CONCURRENT_TASKS")
    max_concurrent_chunks: int = Field(default=10, validation_alias="MAX_CONCURRENT_CHUNKS")
    embedding_batch_size: int = Field(default=32, validation_alias="EMBEDDING_BATCH_SIZE")
    task_timeout: int = Field(default=3600, validation_alias="TASK_TIMEOUT")
    retry_count: int = Field(default=3, validation_alias="TASK_RETRY_COUNT")
    queue_name_prefix: str = Field(default="jusure", validation_alias="QUEUE_NAME_PREFIX")
    consumer_group: str = Field(default="jusure_workers", validation_alias="CONSUMER_GROUP")
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

class Settings(BaseSettings):
    """全局配置"""
    environment: str = Field(default="local", validation_alias="ENVIRONMENT")
    
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    mysql: MySQLConfig = Field(default_factory=MySQLConfig)
    mongodb: MongoDBConfig = Field(default_factory=MongoDBConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    minio: MinIOConfig = Field(default_factory=MinIOConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    task_executor: TaskExecutorConfig = Field(default_factory=TaskExecutorConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    
    # 其他服务地址
    knowledge_service_url: str = Field(default="http://knowledge-service:7101", validation_alias="KNOWLEDGE_SERVICE_URL")
    rag_service_url: str = Field(default="http://rag-service:7102", validation_alias="RAG_SERVICE_URL")
    agent_service_url: str = Field(default="http://agent-service:7103", validation_alias="AGENT_SERVICE_URL")
    parser_service_url: str = Field(default="http://parser-service:7110", validation_alias="PARSER_SERVICE_URL")
    
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()

settings = get_settings()
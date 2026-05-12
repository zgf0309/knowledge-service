# -*- coding: utf-8 -*-
"""Embedding 服务。

默认调用 OpenAI 兼容的远程 embedding 接口，保证文档入库向量和会话检索
向量使用同一个模型；未配置远程接口时再降级到本地 sentence-transformers。
"""
import os

import httpx

from common.utils.logger import get_logger

DEFAULT_EMBEDDING_BASE_URL = os.getenv(
    "DEFAULT_EMBEDDING_BASE_URL",
    "http://114.242.210.44:6300/v1/embeddings",
)
DEFAULT_EMBEDDING_MODEL_NAME = os.getenv("DEFAULT_EMBEDDING_MODEL_NAME", "qwen3-embed-4b")
DEFAULT_EMBEDDING_API_KEY = os.getenv(
    "DEFAULT_EMBEDDING_API_KEY", os.getenv("DEFAULT_LLM_API_KEY", ""), )

logger = get_logger("embedding_service")

class EmbeddingService:
    """轻量级 Embedding 服务"""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        初始化 embedding 服务
        
        Args:
            model_name: 模型名称
                - all-MiniLM-L6-v2: 384 维，速度快，适合英文和代码
                - paraphrase-multilingual-MiniLM-L12-v2: 384 维，支持多语言（包括中文）
                - bge-small-zh-v1.5: 512 维，专为中文优化
        """
        self.model_name = model_name
        self.model = None
        self.dimension = 0
        self.remote_base_url = DEFAULT_EMBEDDING_BASE_URL
        self.remote_model_name = DEFAULT_EMBEDDING_MODEL_NAME
        self.remote_api_key = DEFAULT_EMBEDDING_API_KEY
    
    async def initialize(self):
        """初始化模型（懒加载）"""
        if self.remote_base_url:
            logger.info(f"使用远程 embedding 服务：{self.remote_model_name} @ {self.remote_base_url}")
            return

        if self.model is None:
            try:
                logger.info(f"正在加载 embedding 模型：{self.model_name}")
                from sentence_transformers import SentenceTransformer
                
                self.model = SentenceTransformer(self.model_name)
                self.dimension = self.model.get_sentence_embedding_dimension()
                logger.info(f"Embedding 模型加载完成，维度：{self.dimension}")
            except ImportError:
                logger.error("未安装 sentence-transformers，请运行：pip install sentence-transformers")
                raise
            except Exception as e:
                logger.error(f"加载 embedding 模型失败：{e}")
                raise
    
    async def embed_text(self, text: str) -> list[float]:
        """
        获取单段文本的向量
        
        Args:
            text: 输入文本
            
        Returns:
            向量列表 [0.1, -0.2, 0.3, ...]
        """
        if self.model is None:
            await self.initialize()

        if self.remote_base_url:
            embeddings = await self.embed_texts([text])
            return embeddings[0] if embeddings else []
        
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"生成向量失败：{e}")
            # 返回零向量作为降级方案
            return [0.0] * self.dimension
    
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量获取文本向量
        
        Args:
            texts: 文本列表
            
        Returns:
            向量列表 [[0.1, -0.2, ...], [0.3, -0.4, ...], ...]
        """
        if not texts:
            return []

        if self.model is None:
            await self.initialize()

        if self.remote_base_url:
            try:
                headers = {"Content-Type": "application/json"}
                if self.remote_api_key:
                    headers["Authorization"] = f"Bearer {self.remote_api_key}"
                payload = {"model": self.remote_model_name, "input": texts}
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        self.remote_base_url, headers=headers, json=payload, )
                    response.raise_for_status()
                    data = response.json()

                vectors = [item.get("embedding") or [] for item in data.get("data", [])]
                if vectors:
                    self.dimension = len(vectors[0])
                return vectors
            except Exception as e:
                logger.error(f"远程批量生成向量失败：{e}")
                return []
        
        try:
            embeddings = self.model.encode(
                texts, convert_to_numpy=True, show_progress_bar=len(texts) > 10, batch_size=32
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"批量生成向量失败：{e}")
            # 返回零向量列表作为降级方案
            return [[0.0] * self.dimension for _ in texts]
    
    def get_dimension(self) -> int:
        """获取向量维度"""
        return self.dimension

# 全局单例
_embedding_service: EmbeddingService | None = None

def get_embedding_service(model_name: str = "BAAI/bge-small-zh-v1.5") -> EmbeddingService:
    """
    获取 embedding 服务单例
    
    Args:
        model_name: 模型名称，默认使用中文优化的 BGE 小模型
            - BAAI/bge-small-zh-v1.5: 512 维，专为中文优化，轻量级
            - sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2: 384 维，多语言支持
            - sentence-transformers/all-MiniLM-L6-v2: 384 维，英文和代码
        
    Returns:
        EmbeddingService 实例
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(model_name)
    return _embedding_service

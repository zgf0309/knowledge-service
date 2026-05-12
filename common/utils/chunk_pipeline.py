# -*- coding: utf-8 -*-
"""
chunk_pipeline.py — Chunk Embedding & 向量库写入公共模块

同时提供：
  - 同步版（线程安全，供 batch_parser 等多线程 CLI 使用）
  - 异步版（供 executor.py 等 asyncio 服务使用）

使用方式：
  # 同步（线程内调用）
  from common.utils.chunk_pipeline import EmbeddingModel, embed_chunks, store_chunks

  model = EmbeddingModel("BAAI/bge-m3")
  embed_chunks(chunks, model)
  store_chunks(chunks, index_name="tenant1_kb1")

  # 异步（asyncio 协程内调用）
  from common.utils.chunk_pipeline import aembed_chunks, astore_chunks

  token_count, vector_size = await aembed_chunks(chunks, model_path="BAAI/bge-m3")
  await astore_chunks(chunks, index_name="tenant1_kb1")
"""

import asyncio
import threading
import logging
from typing import Callable, Any

logger = logging.getLogger("chunk_pipeline")

# 每批 embed 的默认大小
_DEFAULT_BATCH = 32
# 每批写库的默认大小
_DEFAULT_STORE_BATCH = 128

# ══════════════════════════════════════════════════════════════════════════════
# 1. Embedding 模型（同步，线程安全懒加载）
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddingModel:
    """
    线程安全的同步 Embedding 模型封装。

    - 懒加载，首次调用 encode() 时才加载模型
    - sentence_transformers 未安装时降级为随机 mock 向量（不中断流程）
    - 支持批量推理，自动截断超长文本
    """

    def __init__(self, model_path: str = "BAAI/bge-m3", max_length: int = 8192, batch_size: int = _DEFAULT_BATCH):
        self.model_path = model_path
        self.max_length = max_length
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    # ── 加载 ──────────────────────────────────────────────────────────────────

    def _load(self):
        """双重检查锁懒加载（线程安全）"""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_path)
                logger.info("[EmbeddingModel] 已加载: %s", self.model_path)
            except ImportError:
                logger.warning("[EmbeddingModel] sentence-transformers 未安装，使用 mock 向量")
                self._model = "mock"
            except Exception as exc:
                logger.warning("[EmbeddingModel] 加载失败: %s，使用 mock 向量", exc)
                self._model = "mock"

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _num_tokens(self, text: str) -> int:
        """估算 token 数（中文字 1 token，其余每 4 字符 1 token）"""
        cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        return cn + (len(text) - cn) // 4

    def _truncate(self, texts: list[str]) -> list[str]:
        """截断超出 max_length 的文本"""
        safe = []
        for t in texts:
            if self._num_tokens(t) > self.max_length:
                safe.append(t[: int(self.max_length * 0.95 * 4)])
            else:
                safe.append(t)
        return safe

    # ── 同步编码 ──────────────────────────────────────────────────────────────

    def encode(self, texts: list[str]) -> list[list[float]]:
        """
        批量编码文本，返回向量列表。

        Returns:
            list[list[float]]  每条文本对应一个向量
        """
        self._load()
        safe = self._truncate(texts)

        if self._model == "mock":
            import random
            return [[random.random() for _ in range(1024)] for _ in safe]

        results = []
        for i in range(0, len(safe), self.batch_size):
            batch = safe[i: i + self.batch_size]
            vecs = self._model.encode(batch).tolist()
            results.extend(vecs)
        return results

    def encode_with_token_count(self, texts: list[str]):
        """
        批量编码文本，同时返回 token 总量（供 executor 计统计）。

        Returns:
            (list[list[float]], int)  向量列表 + token 总量
        """
        self._load()
        safe = self._truncate(texts)

        if self._model == "mock":
            import random
            vecs = [[random.random() for _ in range(1024)] for _ in safe]
            token_count = sum(self._num_tokens(t) for t in safe)
            return vecs, token_count

        results = []
        token_count = 0
        for i in range(0, len(safe), self.batch_size):
            batch = safe[i: i + self.batch_size]
            vecs = self._model.encode(batch).tolist()
            results.extend(vecs)
            token_count += sum(self._num_tokens(t) for t in batch)
        return results, token_count

# ══════════════════════════════════════════════════════════════════════════════
# 2. Chunk → document dict 序列化（唯一维护处）
# ══════════════════════════════════════════════════════════════════════════════

def chunk_to_document(chunk, now_ts_fn: Callable[[], Any]) -> dict:
    """将 Chunk 对象序列化为向量库写入格式"""
    return {
        "id": chunk.id, "content": chunk.content_with_weight, "vector": chunk.metadata.get("vector") if chunk.metadata else None, "metadata": {
            "doc_id": chunk.doc_id, "kb_id": chunk.kb_id, "docnm_kwd": chunk.docnm_kwd, "page_num_int": chunk.page_num_int, "important_kwd": chunk.important_kwd, "question_kwd": chunk.question_kwd, }, "doc_id": chunk.doc_id, "kb_id": chunk.kb_id, "created_at": now_ts_fn(), "updated_at": now_ts_fn(), }

# ══════════════════════════════════════════════════════════════════════════════
# 3. 同步版：embed_chunks / store_chunks
#    适合多线程 CLI（batch_parser.py）
# ══════════════════════════════════════════════════════════════════════════════

def embed_chunks(chunks: list, model: EmbeddingModel) -> int:
    """
    将向量写入每个 chunk.metadata["vector"]（原地修改）。

    Args:
        chunks:  list[Chunk]
        model:   EmbeddingModel 实例

    Returns:
        成功嵌入的 chunk 数量
    """
    if not chunks:
        return 0
    texts = [c.content_with_weight for c in chunks]
    vectors = model.encode(texts)
    for i, chunk in enumerate(chunks):
        if i < len(vectors):
            chunk.metadata = chunk.metadata or {}
            chunk.metadata["vector"] = vectors[i]
    return len(vectors)

def store_chunks(chunks: list, index_name: str, now_ts_fn: Callable | None = None, batch_size: int = _DEFAULT_STORE_BATCH) -> int:
    """
    同步版向量库写入（asyncio.run 包装）。

    Args:
        chunks:      list[Chunk]，metadata["vector"] 必须已填充
        index_name:  目标索引名称，形如 "tenant1_kb1"
        now_ts_fn:   时间戳函数（默认使用 common.utils.now_timestamp）
        batch_size:  每批写入数量，默认 128

    Returns:
        成功写入的文档数量
    """
    try:
        from common.storage import get_vector_store
    except ImportError:
        logger.warning("[store_chunks] common.storage 不可用，跳过写库")
        return 0

    if now_ts_fn is None:
        try:
            from common.utils.helpers import now_timestamp
            now_ts_fn = now_timestamp
        except ImportError:
            import time
            now_ts_fn = lambda: int(time.time() * 1000)

    async def _run():
        vs = get_vector_store()
        dim = 1024
        if chunks and chunks[0].metadata and chunks[0].metadata.get("vector"):
            dim = len(chunks[0].metadata["vector"])
        if not await vs.index_exists(index_name):
            await vs.create_index(index_name, dim)

        documents = [chunk_to_document(c, now_ts_fn) for c in chunks]
        total = 0
        for i in range(0, len(documents), batch_size):
            cnt = await vs.insert(index_name, documents[i: i + batch_size])
            total += cnt or len(documents[i: i + batch_size])
        return total

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("[store_chunks] 写入失败: %s", exc)
        raise

# ══════════════════════════════════════════════════════════════════════════════
# 4. 异步版：aembed_chunks / astore_chunks
#    适合 asyncio 服务（executor.py）
# ══════════════════════════════════════════════════════════════════════════════

async def aembed_chunks(
    chunks: list, model: EmbeddingModel | None = None, model_path: str = "BAAI/bge-m3", batch_size: int = _DEFAULT_BATCH, progress_cb: Callable | None = None, ) -> tuple:
    """
    异步版 Embedding（在线程池中执行，不阻塞事件循环）。

    Args:
        chunks:      list[Chunk]
        model:       已实例化的 EmbeddingModel（优先使用）
        model_path:  model 为 None 时的模型路径
        batch_size:  每批 embed 数量
        progress_cb: 可选进度回调 async callable(prog=float, msg=str)

    Returns:
        (token_count: int, vector_size: int)
        同时原地修改 chunk.metadata["vector"]
    """
    if not chunks:
        return 0, 0

    if model is None:
        model = EmbeddingModel(model_path, batch_size=batch_size)

    contents = [c.content_with_weight for c in chunks]

    if progress_cb:
        await progress_cb(prog=0.7, msg=f"Embedding {len(contents)} chunks...")

    loop = asyncio.get_event_loop()
    vectors, token_count = await loop.run_in_executor(
        None, model.encode_with_token_count, contents
    )

    for i, chunk in enumerate(chunks):
        if i < len(vectors):
            chunk.metadata = chunk.metadata or {}
            chunk.metadata["vector"] = vectors[i]

    vector_size = len(vectors[0]) if vectors else 0

    if progress_cb:
        await progress_cb(prog=0.85, msg=f"Generated {len(vectors)} vectors")

    return token_count, vector_size

async def astore_chunks(
    chunks: list, index_name: str, now_ts_fn: Callable | None = None, batch_size: int = _DEFAULT_STORE_BATCH, progress_cb: Callable | None = None, ) -> bool:
    """
    异步版向量库写入。

    Args:
        chunks:      list[Chunk]，metadata["vector"] 必须已填充
        index_name:  目标索引名称
        now_ts_fn:   时间戳函数
        batch_size:  每批写入数量
        progress_cb: 可选进度回调

    Returns:
        True（成功）
    """
    try:
        from common.storage import get_vector_store
    except ImportError:
        logger.warning("[astore_chunks] common.storage 不可用，跳过写库")
        return False

    if now_ts_fn is None:
        try:
            from common.utils.helpers import now_timestamp
            now_ts_fn = now_timestamp
        except ImportError:
            import time
            now_ts_fn = lambda: int(time.time() * 1000)

    if progress_cb:
        await progress_cb(prog=0.88, msg="Storing chunks to vector database...")

    vector_store = get_vector_store()

    if not await vector_store.index_exists(index_name):
        dim = 1024
        if chunks and chunks[0].metadata and chunks[0].metadata.get("vector"):
            dim = len(chunks[0].metadata["vector"])
        await vector_store.create_index(index_name, dim)

    documents = [chunk_to_document(c, now_ts_fn) for c in chunks]

    for i in range(0, len(documents), batch_size):
        batch = documents[i: i + batch_size]
        await vector_store.insert(index_name, batch)
        if progress_cb:
            stored = min(i + batch_size, len(documents))
            prog = 0.9 + 0.08 * stored / len(documents)
            await progress_cb(prog=prog, msg=f"Stored {stored}/{len(documents)} chunks")

    if progress_cb:
        await progress_cb(prog=0.98, msg="All chunks stored")

    return True
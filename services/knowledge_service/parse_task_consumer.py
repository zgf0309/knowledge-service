# -*- coding: utf-8 -*-
"""
Document Parse Task Consumer - 文档解析任务消费者
监听消息队列中的解析任务，执行文档解析和向量化
"""
import asyncio
import os
from typing import Any, cast
from datetime import datetime

from common.utils import get_logger, generate_id, now_timestamp
from common.storage import get_message_queue, get_object_storage, get_vector_store, redis_conn
from common.models import DocumentModel, TaskModel, ChunkModel, DocumentStatus, TaskStatus
from common.models.database import db_manager
from common.services.embedding_service import get_embedding_service
from services.knowledge_service.services.document_executor_service import DocumentExecutorService
from sqlalchemy import select, update, delete
import json as json_lib

logger = get_logger("parse_task_consumer")

def _index_name(tenant_id: str, kb_id: str) -> str:
    return f"jusure_{tenant_id}_{kb_id}"

class ParseTaskConsumer:
    """解析任务消费者"""
    
    def __init__(self):
        self.mq = None  # 延迟初始化
        self.queue_name = "jusure:task:parse"
        self.group_name = "parse_consumer_group"
        self.consumer_name = f"consumer_{os.getpid()}"
        self.worker_count = max(1, int(os.getenv("PARSE_CONSUMER_WORKERS", "4")))
        
    async def start(self):
        """启动任务消费者"""
        # 确保 Redis 已连接并初始化 MQ
        await redis_conn.connect()
        self.mq = get_message_queue()
            
        logger.info(f"启动文档解析任务消费者，监听队列：{self.queue_name}，并发数：{self.worker_count}")
            
        # 持续监听（consume 方法会自动创建消费组）
        while True:
            try:
                await self._consume_and_process()
            except Exception as e:
                logger.exception(f"消费任务失败：{e}")
                await asyncio.sleep(1)
        
    async def _create_consumer_group(self):
        """创建消费组（已废弃，consume 方法会自动创建）"""
        pass  # consume 方法内部会自动创建
    
    async def _consume_and_process(self):
        """批量消费解析任务，并发执行切片、向量化和 ES 入库。"""
        if self.mq is None:
            return
        messages = await self.mq.consume(
            queue_name=self.queue_name, group_name=self.group_name, consumer_name=self.consumer_name, count=self.worker_count, block=5000  # 阻塞 5 秒
        )
        
        if not messages:
            return
        
        await asyncio.gather(*(self._process_message(message) for message in messages))

    async def _process_message(self, message: dict[str, Any]):
        """处理单条解析消息。每个任务独立 session，可安全并发。"""
        if self.mq is None:
            return
        try:
            task_id = message.get("task_id")
            doc_id = message.get("doc_id")
            kb_id = message.get("kb_id")
            tenant_id = message.get("tenant_id")
            message_id = message.get("_msg_id")

            if not all(isinstance(value, str) and value for value in (task_id, doc_id, kb_id, tenant_id)):
                raise ValueError(f"解析任务消息缺少必要字段：{message}")
            task_id = cast(str, task_id)
            doc_id = cast(str, doc_id)
            kb_id = cast(str, kb_id)
            tenant_id = cast(str, tenant_id)

            logger.info(f"[{task_id}] 收到解析任务，doc_id={doc_id}, kb_id={kb_id}")

            await self._execute_parse_task(
                task_id=task_id, doc_id=doc_id, kb_id=kb_id, tenant_id=tenant_id
            )

            if isinstance(message_id, str) and message_id:
                await self.mq.ack(
                    queue_name=self.queue_name, group_name=self.group_name, msg_id=message_id
                )

        except Exception as e:
            logger.exception(f"处理消息失败：{e}")
            # 失败消息不 ack，保留在 Redis Stream pending 中便于后续补偿。
    
    async def _execute_parse_task(
        self, task_id: str, doc_id: str, kb_id: str, tenant_id: str
    ):
        """执行文档解析任务"""
        # 确保 db_manager 已初始化
        if not db_manager.engine:
            await db_manager.init()
        
        # 使用 db_manager 创建 session
        async with db_manager.get_session() as session:
            try:
                # ========== Step 1: 更新任务状态为运行中 ==========
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=0, progress_msg="开始解析文档"
                )
                await self._update_document_status(
                    session, doc_id, DocumentStatus.PARSING.value, progress=0, progress_msg="开始解析文档"
                )
                
                # ========== Step 2: 获取文档信息 ==========
                doc_stmt = select(DocumentModel).where(DocumentModel.id == doc_id)
                doc_result = await session.execute(doc_stmt)
                doc = doc_result.scalar_one_or_none()
                
                if not doc:
                    raise ValueError(f"文档不存在：{doc_id}")
                
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=10, progress_msg=f"读取文档：{doc.name}"
                )
                
                # ========== Step 3: 从 OSS 读取文档内容 ==========
                storage = get_object_storage()
                doc_name = cast(str | None, doc.name) or ""
                doc_location = cast(str | None, doc.location) or cast(str | None, doc.source_url) or ""  # OSS/MinIO/本地路径，web 导入可为 source_url
                doc_type = cast(str | None, doc.type) or ""
                parser_config = cast(dict[str, Any] | None, doc.parser_config)
                
                logger.info(f"[{doc_id}] 从 OSS 读取文档：{doc_location}")
                
                # 提取文件类型。导入接口里 doc.type 可能是 text，需要优先相信文件名后缀。
                file_type = self._guess_file_type(doc_name, doc_location, doc_type)
                
                # 读取文档内容
                content = await self._read_document_content(storage, doc_location, file_type)
                
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=30, progress_msg="文档读取完成，开始解析"
                )
                await self._update_document_status(
                    session, doc_id, DocumentStatus.PARSING.value, progress=30, progress_msg="文档读取完成，开始解析"
                )
                
                # ========== Step 4: 执行文档解析和分块 ==========
                executor = DocumentExecutorService(session)
                
                parse_result = await executor.execute(
                    tenant_id=tenant_id, doc_id=doc_id, kb_id=kb_id, content=content, enable_cleaning=False, # 暂时禁用清洗
                    parser_config=parser_config
                )
                
                chunks = parse_result.get("chunks", [])
                total_chunks = len(chunks)
                total_tokens = parse_result.get("total_tokens", 0)
                
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=60, progress_msg=f"解析完成，生成 {total_chunks} 个切片"
                )
                
                # ========== Step 5: 保存切片到数据库 ==========
                logger.info(f"[{doc_id}] 保存 {total_chunks} 个切片到数据库")
                
                await self._save_chunks(
                    session, doc_id, kb_id, tenant_id, chunks
                )
                
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=80, progress_msg="切片保存完成"
                )
                await self._update_document_status(
                    session, doc_id, DocumentStatus.PARSING.value, chunk_count=total_chunks, token_num=total_tokens, progress=80, progress_msg="切片保存完成，开始向量化"
                )
                
                # ========== Step 6: 向量化 ==========
                logger.info(f"[{doc_id}] 开始向量化处理")
                
                embedding_service = get_embedding_service()
                await self._embedding_chunks(
                    session, doc_id, kb_id, tenant_id, chunks, embedding_service
                )
                
                await self._update_task_status(
                    session, task_id, TaskStatus.RUNNING.value, progress=95, progress_msg="向量化完成"
                )
                await self._update_document_status(
                    session, doc_id, DocumentStatus.PARSING.value, chunk_count=total_chunks, token_num=total_tokens, progress=95, progress_msg="向量化完成，等待完成入库"
                )
                
                # ========== Step 7: 更新文档状态 ==========
                await self._update_document_status(
                    session, doc_id, DocumentStatus.COMPLETED.value, chunk_count=total_chunks,
                    token_num=total_tokens, progress=100, progress_msg="解析完成"
                )
                
                await self._update_task_status(
                    session, task_id, TaskStatus.COMPLETED.value, progress=100, progress_msg="任务完成"
                )
                
                logger.info(f"[{task_id}] 文档解析任务完成！doc_id={doc_id}, chunks={total_chunks}, tokens={total_tokens}")
                
            except Exception as e:
                logger.exception(f"[{task_id}] 解析失败：{e}")
                
                # 更新为失败状态
                await self._update_task_status(
                    session, task_id, TaskStatus.FAILED.value, progress=0, progress_msg=f"解析失败：{str(e)}", error_msg=str(e)
                )
                
                await self._update_document_status(
                    session, doc_id, DocumentStatus.FAILED.value, progress_msg=f"解析失败：{str(e)}"
                )
    
    async def _read_document_content(
        self, storage, location: str, file_type: str
    ) -> str:
        """读取文档内容"""
        if not location:
            logger.error("文档位置为空，无法读取内容")
            return ""

        # 如果是本地文件路径
        if location.startswith("/"):
            logger.info(f"[{location}] 从本地路径读取文件")
            
            # 检查文件是否存在
            if not os.path.exists(location):
                logger.error(f"文件不存在：{location}")
                return ""
            
            # 根据文件类型使用不同的解析器
            if file_type.lower() in ['docx', 'doc']:
                logger.info(f"使用 DOCX 解析器：{location}")
                return await self._parse_docx_with_ragflow(location)
            elif file_type.lower() == 'pdf':
                # TODO: PDF 解析
                logger.warning(f"PDF 文件需要专门解析器，尝试简单读取")
                try:
                    with open(location, 'rb') as f:
                        content = f.read()
                        # 简单的文本提取（效果不好，仅用于测试）
                        return content.decode('utf-8', errors='ignore')
                except Exception as e:
                    logger.error(f"PDF 读取失败：{e}")
                    return ""
            else:
                # 纯文本文件
                logger.info(f"使用文本读取器：{location}")
                try:
                    with open(location, 'r', encoding='utf-8') as f:
                        return f.read()
                except UnicodeDecodeError:
                    # 尝试其他编码
                    with open(location, 'r', encoding='gbk') as f:
                        return f.read()
        
        # 如果是 MinIO HTTP URL（http://localhost:9000/bucket/path）
        if location.startswith("http://") or location.startswith("https://"):
            logger.info(f"[{location}] 从 MinIO HTTP URL 读取文件")
            try:
                # 解析 URL 提取 bucket 和 object_name
                from urllib.parse import urlparse, unquote
                parsed = urlparse(location)
                path_parts = parsed.path.lstrip('/').split('/', 1)

                if file_type.lower() in {"html", "htm", "web"} or len(path_parts) != 2:
                    import httpx

                    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                        response = await client.get(location)
                        response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" in content_type or file_type.lower() in {"html", "htm", "web"}:
                        return self._html_to_text(response.text)
                    return response.text

                if len(path_parts) == 2:
                    bucket = path_parts[0]
                    object_name = unquote(path_parts[1])
                    
                    logger.info(f"从 MinIO 读取：bucket={bucket}, object={object_name}")
                    content = await storage.get(bucket, object_name)
                    
                    # 根据文件类型处理
                    if file_type.lower() in ['docx', 'doc']:
                        # 写入临时文件后解析
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=f'.{file_type}', delete=False) as tmp:
                            tmp.write(content)
                            tmp_path = tmp.name
                        
                        try:
                            return await self._parse_docx_with_ragflow(tmp_path)
                        finally:
                            os.unlink(tmp_path)
                    else:
                        return content.decode('utf-8', errors='ignore')
                else:
                    logger.error(f"无法解析 MinIO URL: {location}")
                    return ""
            except Exception as e:
                logger.error(f"MinIO URL 读取失败：{e}")
                return ""
        
        # 如果是 OSS 路径（oss://bucket/path）
        if location.startswith("oss://"):
            logger.info(f"[{location}] 从 OSS 路径读取文件")
            try:
                # 解析 OSS 路径
                path_parts = location[6:].split('/', 1)  # 去掉 oss://
                if len(path_parts) == 2:
                    bucket = path_parts[0]
                    object_name = path_parts[1]
                    
                    content = await storage.get(bucket, object_name)
                    
                    # 根据文件类型处理
                    if file_type.lower() in ['docx', 'doc']:
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=f'.{file_type}', delete=False) as tmp:
                            tmp.write(content)
                            tmp_path = tmp.name
                        
                        try:
                            return await self._parse_docx_with_ragflow(tmp_path)
                        finally:
                            os.unlink(tmp_path)
                    else:
                        return content.decode('utf-8', errors='ignore')
            except Exception as e:
                logger.error(f"OSS 路径读取失败：{e}")
                return ""
        
        # 其他情况，尝试直接读取
        logger.warning(f"无法识别的文档位置格式：{location}")
        return ""

    def _html_to_text(self, html: str) -> str:
        """基础 HTML 文本抽取，供 web 导入后续切片使用。"""
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.skip_depth = 0
                self.parts = []

            def handle_starttag(self, tag, attrs):
                if tag in {"script", "style", "noscript"}:
                    self.skip_depth += 1
                if tag in {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
                    self.parts.append("\n")

            def handle_endtag(self, tag):
                if tag in {"script", "style", "noscript"} and self.skip_depth:
                    self.skip_depth -= 1
                if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
                    self.parts.append("\n")

            def handle_data(self, data):
                if not self.skip_depth:
                    text = data.strip()
                    if text:
                        self.parts.append(text)

        parser = TextExtractor()
        parser.feed(html or "")
        lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
        return "\n".join(line for line in lines if line)

    def _guess_file_type(self, doc_name: str = "", location: str = "", doc_type: str = "") -> str:
        """从文件名/URL 推断真实扩展名，避免 doc.type=text 时误读 DOCX/PDF 二进制。"""
        from urllib.parse import unquote, urlparse

        candidates = [doc_name or ""]
        if location:
            parsed = urlparse(location)
            candidates.append(unquote(parsed.path or location))

        for candidate in candidates:
            filename = candidate.rsplit("/", 1)[-1].split("?", 1)[0]
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower()
                if ext:
                    return ext

        return (doc_type or "txt").lower()
    
    async def _parse_docx_with_ragflow(self, file_path: str) -> str:
        """使用 ragflow 的 parser 读取 DOCX 文件"""
        try:
            from importlib import import_module

            RAGFlowParser = import_module("module.parseres.ragflow_parser").RAGFlowParser
            parser = RAGFlowParser()
            result = await parser.parse(file_path, parser_config={})
            
            # 提取文本内容
            content = ""
            for chunk in result.get("chunks", []):
                content += chunk.get("content_with_weight", "") + "\n"
            
            return content.strip()
        except Exception as e:
            logger.warning(f"ragflow parser 失败：{e}，尝试使用 python-docx")
            # Fallback: 使用 python-docx
            return self._parse_docx_simple(file_path)
    
    def _parse_docx_simple(self, file_path: str) -> str:
        """简单的 DOCX 解析（fallback）"""
        try:
            from docx import Document
            
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except Exception as e:
            logger.error(f"python-docx 解析失败：{e}")
            return ""
    
    async def _save_chunks(
        self, session, doc_id: str, kb_id: str, tenant_id: str, chunks: list[dict[str, Any]]
    ):
        """保存切片到数据库"""
        await session.execute(delete(ChunkModel).where(ChunkModel.doc_id == doc_id))
        await session.flush()

        for i, chunk_data in enumerate(chunks):
            chunk = ChunkModel(  # pyright: ignore[reportCallIssue]
                id=generate_id("chunk"), tenant_id=tenant_id, kb_id=kb_id, doc_id=doc_id, content=chunk_data.get("content", ""), content_with_weight=chunk_data.get("content_with_weight", ""), # 使用 LONGTEXT 字段
                position=str(i), # 使用字符串类型
                create_time=now_timestamp(), )
            session.add(chunk)
        
        await session.flush()
        logger.info(f"成功保存 {len(chunks)} 个切片")
    
    async def _embedding_chunks(
        self, session, doc_id: str, kb_id: str, tenant_id: str, chunks: list[dict[str, Any]], embedding_service
    ):
        """对切片进行向量化并更新到数据库"""
        try:
            # 提取所有切片的文本内容
            texts_to_embed = []
            chunk_positions = []
            
            for i, chunk_data in enumerate(chunks):
                content = chunk_data.get("content", "")
                if content and len(content.strip()) > 0:
                    texts_to_embed.append(content)
                    chunk_positions.append(i)
            
            if not texts_to_embed:
                logger.warning(f"[{doc_id}] 没有需要向量化的文本")
                return
            
            # 批量生成向量
            logger.info(f"[{doc_id}] 正在为 {len(texts_to_embed)} 个切片生成向量")
            embeddings = await embedding_service.embed_texts(texts_to_embed)
            
            # 更新数据库中的向量字段，并准备同步到 Elasticsearch。
            from sqlalchemy import select

            es_documents: list[dict[str, Any]] = []
            
            for position, vector in zip(chunk_positions, embeddings):
                # 查询对应的 chunk
                stmt = select(ChunkModel).where(
                    ChunkModel.doc_id == doc_id, ChunkModel.position == str(position)
                )
                result = await session.execute(stmt)
                chunk = result.scalar_one_or_none()
                
                if chunk:
                    chunk.vector = json_lib.dumps(vector)  # 将向量列表转为 JSON 字符串
                    chunk.vector_dim = len(vector)  # 记录向量维度
                    chunk_metadata = cast(dict[str, Any] | None, chunk.chunk_metadata) or {}
                    chunk_id = cast(str, chunk.id)
                    chunk_content = cast(str | None, chunk.content) or cast(str | None, chunk.content_with_weight) or ""
                    chunk_status = cast(str | None, chunk.status)
                    chunk_type = cast(str | None, chunk.chunk_type) or "original"
                    chunk_position = cast(str | None, chunk.position)
                    chunk_page_num = cast(int | None, chunk.page_num)
                    es_documents.append({
                        "id": chunk_id, "tenant_id": tenant_id, "kb_id": kb_id, "knowledge_id": kb_id, "doc_id": doc_id, "chunk_id": chunk_id, "content": chunk_content, "vector": vector, "status": chunk_status, "chunk_type": chunk_type, "metadata": {
                            **chunk_metadata, "tenant_id": tenant_id, "kb_id": kb_id, "doc_id": doc_id, "chunk_id": chunk_id, "position": chunk_position, "page_num": chunk_page_num, "vector_dim": len(vector), }, "created_at": datetime.utcnow().isoformat(), "updated_at": datetime.utcnow().isoformat(), })
            
            await session.commit()
            logger.info(f"[{doc_id}] 向量化完成，共处理 {len(embeddings)} 个向量，维度：{len(embeddings[0]) if embeddings else 0}")

            if es_documents:
                await self._store_chunks_to_es(tenant_id, kb_id, doc_id, es_documents)
            
        except Exception as e:
            logger.error(f"[{doc_id}] 向量化失败：{e}")
            raise

    async def _store_chunks_to_es(
        self, tenant_id: str, kb_id: str, doc_id: str, documents: list[dict[str, Any]], ):
        """将已向量化切片同步到 Elasticsearch，供知识库向量检索使用。"""
        try:
            vector_store = get_vector_store()
            index_name = _index_name(tenant_id, kb_id)
            dimension = len(documents[0].get("vector") or [])
            if not dimension:
                logger.warning(f"[{doc_id}] ES 写入跳过：向量维度为空")
                return

            if not await vector_store.index_exists(index_name):
                await vector_store.create_index(index_name, dimension)
            else:
                existing = await vector_store.search(
                    index_name, top_k=5000, filters={"doc_id": doc_id}, )
                old_ids = [item.get("id") for item in existing.get("hits", []) if item.get("id")]
                if old_ids:
                    await vector_store.delete(index_name, old_ids)

            inserted = await vector_store.insert(index_name, documents)
            logger.info(f"[{doc_id}] 已同步 {inserted} 个向量切片到 ES 索引 {index_name}")
        except Exception as e:
            logger.exception(f"[{doc_id}] 同步向量到 ES 失败：{e}")
            raise
    
    async def _update_task_status(
        self, session, task_id: str, status: str, progress: int = 0, progress_msg: str | None = None, error_msg: str | None = None
    ):
        """更新任务状态"""
        update_data: dict[str, Any] = {
            "status": status, "progress": progress, }
        
        if progress_msg:
            update_data["progress_msg"] = progress_msg
        
        if error_msg:
            update_data["error_msg"] = error_msg
        
        stmt = update(TaskModel).where(TaskModel.id == task_id).values(**update_data)
        await session.execute(stmt)
    
    async def _update_document_status(
        self, session, doc_id: str, status: str, chunk_count: int | None = None,
        token_num: int | None = None, progress: int | None = None, progress_msg: str | None = None
    ):
        """更新文档状态"""
        update_data: dict[str, Any] = {"status": status}
        
        if chunk_count is not None:
            update_data["chunk_count"] = chunk_count
        
        if token_num is not None:
            update_data["token_num"] = token_num
        
        if progress is not None:
            update_data["progress"] = progress
        
        if progress_msg is not None:
            update_data["progress_msg"] = progress_msg
        
        stmt = update(DocumentModel).where(DocumentModel.id == doc_id).values(**update_data)
        await session.execute(stmt)

async def main():
    """主函数"""
    consumer = ParseTaskConsumer()
    await consumer.start()

if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.utils.logger import get_logger
from .document_clean_service import (
    DocumentCleanTaskService,
    DocumentRuleRelationService,
    KnowledgeRulePresetService,
)

logger = get_logger("document_executor")

class DocumentExecutorService:
    """文档执行服务
    
    核心流程：
    1. 文档读取（从 OSS 获取内容）
    2. 文档清洗（可选，根据配置决定是否启用）
    3. 文档解析（使用对应的 parser）
    4. 文档分块（按 chunk_size 和 chunk_overlap）
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.clean_task_service = DocumentCleanTaskService(db)
        self.rule_relation_service = DocumentRuleRelationService(db)
        self.preset_service = KnowledgeRulePresetService(db)
    
    async def execute(
        self, tenant_id: str, doc_id: str, kb_id: str, content: str, enable_cleaning: bool = True, clean_rules: list[dict[str, Any]] | None = None, parser_config: dict[str, Any] | None = None, ) -> dict[str, Any]:
        """执行文档处理全流程
        
        Args:
            tenant_id: 租户 ID
            doc_id: 文档 ID
            kb_id: 知识库 ID
            content: 文档原始内容
            enable_cleaning: 是否启用清洗（默认 True）
            clean_rules: 清洗规则列表（可选，为空则使用知识库预配置）
            parser_config: 解析配置（chunk_size, chunk_overlap 等）
        
        Returns:
            {
                "chunks": [...], # 分块结果
                "cleaned": True/False, # 是否经过清洗
                "clean_task_id": "...", # 清洗任务 ID（如果启用了清洗）
                "total_chunks": 10, # 总切片数
                "total_tokens": 5000, # 总 token 数
            }
        """
        result = {
            "chunks": [], "cleaned": False, "total_chunks": 0, "total_tokens": 0, }
        
        try:
            # ========== Step 1: 文档清洗（可选流程）==========
            if enable_cleaning:
                logger.info(f"[{doc_id}] 启动文档清洗流程")
                
                # 如果没有提供规则，使用知识库预配置
                if not clean_rules:
                    logger.info(f"[{doc_id}] 使用知识库预配置规则")
                    preset_rules = await self.preset_service.get_knowledge_presets(kb_id, tenant_id)
                    
                    # 检查文档是否有专属规则
                    doc_rules = await self.rule_relation_service.get_document_rules(doc_id, tenant_id)
                    if doc_rules:
                        logger.info(f"[{doc_id}] 使用文档专属规则")
                        clean_rules = doc_rules
                    else:
                        clean_rules = preset_rules
                
                # 执行清洗
                if clean_rules:
                    logger.info(f"[{doc_id}] 应用 {len(clean_rules)} 条清洗规则")
                    
                    # 创建清洗任务记录
                    task_id = await self.clean_task_service.create_task({
                        "tenant_id": tenant_id, "knowledge_id": kb_id, "document_id": doc_id, "task_type": "clean", "original_url": "", "rules_applied": clean_rules,
                    })
                    await self.clean_task_service.update_task_state(
                        task_id=task_id, state="running", progress=0
                    )
                    
                    # 执行清洗逻辑
                    cleaned_content = await self.clean_task_service.execute_cleaning(
                        content=content, rules=clean_rules, aigc_model_id=None  # 如果需要 LLM 处理，传入 model_id
                    )
                    
                    # 更新任务状态
                    await self.clean_task_service.update_task_state(
                        task_id=task_id, state="completed", progress=100, cleaned_content=cleaned_content, rules_applied=clean_rules, )
                    
                    # 使用清洗后的内容
                    content = cleaned_content
                    result["cleaned"] = True
                    result["clean_task_id"] = task_id
                    
                    logger.info(f"[{doc_id}] 文档清洗完成，task_id={task_id}")
                else:
                    logger.info(f"[{doc_id}] 未找到清洗规则，跳过清洗")
            else:
                logger.info(f"[{doc_id}] 清洗功能已禁用，跳过清洗流程")
            
            # ========== Step 2: 文档解析和分块 ==========
            logger.info(f"[{doc_id}] 开始文档解析和分块")
            
            # TODO: 实际应该调用 Parser 进行解析
            # 这里先实现简单的文本分块逻辑作为示例
            
            parser_config = parser_config or {}
            chunk_size = parser_config.get("chunk_size", 256)
            chunk_overlap = parser_config.get("chunk_overlap", 20)
            
            # 简单分块（实际应该使用更智能的 parser）
            chunks = self._simple_chunk(content, chunk_size, chunk_overlap)
            
            result["chunks"] = chunks
            result["total_chunks"] = len(chunks)
            result["total_tokens"] = sum(len(chunk.get("content_with_weight", "")) for chunk in chunks)
            
            logger.info(f"[{doc_id}] 文档分块完成，共 {len(chunks)} 个 chunk")
            
            return result
            
        except Exception as e:
            logger.exception(f"[{doc_id}] 文档处理失败：{e}")
            raise
    
    def _simple_chunk(self, text: str, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
        """简单文本分块（示例实现）
        
        实际应该替换为智能 parser，支持：
        - 按段落分块
        - 按语义分块
        - 按标题层级分块
        """
        chunks = []
        
        # 按换行符分割
        paragraphs = text.split('\n\n')
        
        current_chunk = ""
        current_pos = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 如果当前段落 + 已有内容超过 chunk_size，创建新 chunk
            if len(current_chunk) + len(para) > chunk_size:
                # 保存当前 chunk
                if current_chunk:
                    chunks.append({
                        "content_with_weight": current_chunk.strip(), "content": current_chunk.strip(), "position": current_pos, })
                    current_pos += 1
                
                # 如果段落本身超过 chunk_size，需要进一步切分
                if len(para) > chunk_size:
                    # 按句子切分
                    sentences = para.replace('。', '。\n').replace('！', '！\n').replace('？', '？\n').split('\n')
                    current_chunk = ""
                    
                    for sent in sentences:
                        if len(current_chunk) + len(sent) <= chunk_size:
                            current_chunk += sent
                        else:
                            if current_chunk:
                                chunks.append({
                                    "content_with_weight": current_chunk.strip(), "content": current_chunk.strip(), "position": current_pos, })
                                current_pos += 1
                            current_chunk = sent
                else:
                    current_chunk = para
            else:
                current_chunk += "\n" + para if current_chunk else para
        
        # 添加最后一个 chunk
        if current_chunk:
            chunks.append({
                "content_with_weight": current_chunk.strip(), "content": current_chunk.strip(), "position": current_pos, })
        
        return chunks

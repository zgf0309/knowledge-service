# -*- coding: utf-8 -*-
"""
Document Cleaning Service - 文档清洗服务层
提供文档清洗规则管理、任务执行和进度查询功能

流程定位：文档读取 → 文档清洗 → 文档切片
"""
import time
import re
import unicodedata
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from common.utils import get_logger

logger = get_logger("document_clean_service")

class DocumentCleanRuleService:
    """文档清洗规则服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def list_rules(
        self, tenant_id: str | None, rule_type: int | None = None, doc_type: int | None = None, is_builtin: bool | None = None, page: int = 1, page_size: int = 10, ) -> dict[str, Any]:
        """获取清洗规则列表"""
        from common.models import DocumentCleanRule
        
        query = select(DocumentCleanRule).where(DocumentCleanRule.tenant_id == tenant_id)
        
        if rule_type is not None:
            query = query.where(DocumentCleanRule.rule_type == rule_type)
        if doc_type is not None:
            query = query.where(DocumentCleanRule.doc_type == doc_type)
        if is_builtin is not None:
            query = query.where(DocumentCleanRule.is_builtin == (1 if is_builtin else 0))
        
        result = await self.db.execute(query)
        all_rules = result.scalars().all()
        
        # 分页
        total = len(all_rules)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        rules = all_rules[start_idx:end_idx]
        
        return {
            "list": [rule.to_dict() for rule in rules], "total": total, "page_no": page, "page_size": page_size, }
    
    async def create_rule(self, data: dict[str, Any]) -> str:
        """创建清洗规则"""
        from common.models import DocumentCleanRule
        from common.utils import generate_id
        
        now = int(time.time() * 1000)
        rule = DocumentCleanRule(  # pyright: ignore[reportCallIssue]
            id=generate_id(), tenant_id=data["tenant_id"], rule_name=data["rule_name"], rule_content=data["rule_content"], rule_desc=data.get("rule_desc", ""), rule_type=data.get("rule_type", 0), doc_type=data.get("doc_type", 0), is_builtin=data.get("is_builtin", 0), created_by=data.get("created_by"), create_time=now, update_time=now, )
        
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        
        return rule.id
    
    async def update_rule(self, rule_id: str, tenant_id: str | None, data: dict[str, Any]) -> bool:
        """更新清洗规则"""
        from common.models import DocumentCleanRule
        
        query = select(DocumentCleanRule).where(
            DocumentCleanRule.id == rule_id, DocumentCleanRule.tenant_id == tenant_id
        )
        result = await self.db.execute(query)
        rule = result.scalar_one_or_none()
        
        if not rule:
            return False
        
        for key, value in data.items():
            if hasattr(rule, key) and value is not None:
                setattr(rule, key, value)
        
        rule.update_time = int(time.time() * 1000)
        await self.db.commit()
        return True
    
    async def delete_rule(self, rule_id: str, tenant_id: str | None) -> bool:
        """删除清洗规则"""
        from common.models import DocumentCleanRule
        
        query = select(DocumentCleanRule).where(
            DocumentCleanRule.id == rule_id, DocumentCleanRule.tenant_id == tenant_id
        )
        result = await self.db.execute(query)
        rule = result.scalar_one_or_none()
        
        if not rule:
            return False
        
        await self.db.delete(rule)
        await self.db.commit()
        return True
    
    async def get_builtin_rules(self, doc_type: int | None = None) -> list[Any]:
        """获取内置规则"""
        from common.models import DocumentCleanRule
        
        query = select(DocumentCleanRule).where(
            DocumentCleanRule.is_builtin == 1
        )
        
        if doc_type is not None:
            query = query.where(DocumentCleanRule.doc_type == doc_type)
        
        result = await self.db.execute(query)
        return result.scalars().all()

class DocumentRuleRelationService:
    """文档与规则关联服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_document_rules(self, document_id: str, tenant_id: str | None) -> list[Any]:
        """获取文档关联的清洗规则"""
        from common.models import DocumentRuleRelation, DocumentCleanRule
        
        query = select(DocumentRuleRelation, DocumentCleanRule).join(
            DocumentCleanRule, DocumentRuleRelation.rule_id == DocumentCleanRule.id
        ).where(
            DocumentRuleRelation.document_id == document_id, DocumentRuleRelation.tenant_id == tenant_id, DocumentRuleRelation.enabled == 1
        ).order_by(DocumentRuleRelation.priority)
        
        result = await self.db.execute(query)
        relations = result.all()
        
        return [{
            "relation_id": rel[0].id, "rule_id": rel[0].rule_id, "rule_type": rel[0].rule_type, "priority": rel[0].priority, "rule_name": rel[1].rule_name, "rule_content": rel[1].rule_content, } for rel in relations]
    
    async def add_relation(self, data: dict[str, Any]) -> str:
        """添加文档规则关联"""
        from common.models import DocumentRuleRelation
        from common.utils import generate_id
        
        now = int(time.time() * 1000)
        relation = DocumentRuleRelation(  # pyright: ignore[reportCallIssue]
            id=generate_id(), tenant_id=data["tenant_id"], document_id=data["document_id"], rule_id=data["rule_id"], rule_type=data.get("rule_type", 0), priority=data.get("priority", 0), enabled=data.get("enabled", 1), create_time=now, )
        
        self.db.add(relation)
        await self.db.commit()
        await self.db.refresh(relation)
        
        return relation.id
    
    async def remove_relation(self, document_id: str, rule_id: str, tenant_id: str | None) -> bool:
        """移除文档规则关联"""
        from common.models import DocumentRuleRelation
        
        query = select(DocumentRuleRelation).where(
            DocumentRuleRelation.document_id == document_id, DocumentRuleRelation.rule_id == rule_id, DocumentRuleRelation.tenant_id == tenant_id
        )
        result = await self.db.execute(query)
        relation = result.scalar_one_or_none()
        
        if not relation:
            return False
        
        await self.db.delete(relation)
        await self.db.commit()
        return True

class KnowledgeRulePresetService:
    """知识库预配置规则服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_knowledge_presets(self, knowledge_id: str, tenant_id: str | None) -> list[Any]:
        """获取知识库预配置的清洗规则"""
        from common.models import KnowledgeRulePreset, DocumentCleanRule
        
        query = select(KnowledgeRulePreset, DocumentCleanRule).join(
            DocumentCleanRule, KnowledgeRulePreset.rule_id == DocumentCleanRule.id
        ).where(
            KnowledgeRulePreset.knowledge_id == knowledge_id, KnowledgeRulePreset.tenant_id == tenant_id, KnowledgeRulePreset.enabled == 1
        )
        
        result = await self.db.execute(query)
        presets = result.all()
        
        return [{
            "preset_id": preset[0].id, "rule_id": preset[0].rule_id, "rule_type": preset[0].rule_type, "rule_name": preset[1].rule_name, "rule_content": preset[1].rule_content, } for preset in presets]
    
    async def add_preset(self, knowledge_id: str, rule_ids: list[str], tenant_id: str | None) -> list[str]:
        """添加知识库预配置规则"""
        from common.models import KnowledgeRulePreset
        from common.utils import generate_id
        
        preset_ids = []
        for rule_id in rule_ids:
            now = int(time.time() * 1000)
            preset = KnowledgeRulePreset(  # pyright: ignore[reportCallIssue]
                id=generate_id(), tenant_id=tenant_id, knowledge_id=knowledge_id, rule_id=rule_id, rule_type=0, # 默认脚本类型
                enabled=1, create_time=now, )
            self.db.add(preset)
            preset_ids.append(preset.id)
        
        await self.db.commit()
        return preset_ids
    
    async def update_presets(
        self, knowledge_id: str, new_rule_ids: list[str], old_rule_ids: list[str], tenant_id: str | None
    ) -> bool:
        """更新知识库预配置规则（先删后增）"""
        from common.models import KnowledgeRulePreset
        
        # 删除旧的
        delete_query = select(KnowledgeRulePreset).where(
            KnowledgeRulePreset.knowledge_id == knowledge_id, KnowledgeRulePreset.rule_id.in_(old_rule_ids), KnowledgeRulePreset.tenant_id == tenant_id
        )
        result = await self.db.execute(delete_query)
        old_presets = result.scalars().all()
        
        for preset in old_presets:
            await self.db.delete(preset)
        
        # 添加新的
        return await self.add_preset(knowledge_id, new_rule_ids, tenant_id)

class DocumentCleanTaskService:
    """文档清洗任务服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_task(self, data: dict[str, Any]) -> str:
        """创建清洗任务"""
        from common.models import DocumentCleanTask
        from common.utils import generate_id
        
        now = int(time.time() * 1000)
        task = DocumentCleanTask(  # pyright: ignore[reportCallIssue]
            id=generate_id(), tenant_id=data["tenant_id"], knowledge_id=data["knowledge_id"], document_id=data["document_id"], task_type=data.get("task_type", "clean"), state="pending", progress=0, original_url=data.get("original_url"), aigc_model_id=data.get("aigc_model_id"), rules_applied=data.get("rules_applied", []), create_time=now, )
        
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        
        return task.id
    
    async def update_task_state(
        self, task_id: str, state: str, progress: float | None = None, progress_msg: str | None = None, error_msg: str | None = None, cleaned_url: str | None = None, cleaned_content: str | None = None, rules_applied: list[dict[str, Any]] | None = None, ) -> bool:
        """更新任务状态"""
        from common.models import DocumentCleanTask
        
        query = select(DocumentCleanTask).where(DocumentCleanTask.id == task_id)
        result = await self.db.execute(query)
        task = result.scalar_one_or_none()
        
        if not task:
            return False
        
        task.state = state
        
        if progress is not None:
            task.progress = progress
        if progress_msg is not None:
            task.progress_msg = progress_msg
        if error_msg is not None:
            task.error_msg = error_msg
        if cleaned_url is not None:
            task.cleaned_url = cleaned_url
        if cleaned_content is not None:
            task.cleaned_content = cleaned_content
        if rules_applied is not None:
            task.rules_applied = rules_applied
        
        if state in ["completed", "failed"]:
            task.end_time = int(time.time() * 1000)
        
        if state == "running" and task.start_time is None:
            task.start_time = int(time.time() * 1000)
        
        await self.db.commit()
        return True
    
    async def get_task(self, task_id: str, tenant_id: str | None) -> Any | None:
        """获取任务详情"""
        from common.models import DocumentCleanTask
        
        query = select(DocumentCleanTask).where(
            DocumentCleanTask.id == task_id, DocumentCleanTask.tenant_id == tenant_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def execute_cleaning(
        self, content: str, rules: list[dict[str, Any]], aigc_model_id: str | None = None
    ) -> str:
        """执行文档清洗逻辑
        
        Args:
            content: 原始文档内容
            rules: 规则列表，每个规则包含 rule_type 和 rule_content
            aigc_model_id: AI 模型 ID（用于模型处理类型）
        
        Returns:
            清洗后的内容
        """
        cleaned_content = content
        
        for rule in rules:
            rule_type = rule.get("rule_type", 0)
            rule_content = rule.get("rule_content", "")
            
            if rule_type == 0:
                # 脚本处理：使用正则表达式或字符串操作
                cleaned_content = self._apply_script_rule(cleaned_content, rule_content)
            elif rule_type == 1 and aigc_model_id:
                # 模型处理：调用 LLM
                cleaned_content = await self._apply_llm_rule(cleaned_content, rule_content, aigc_model_id)
        
        return cleaned_content
    
    def _detect_language(self, text: str) -> str:
        """智能检测文档语言
        
        Args:
            text: 待检测的文本
        
        Returns:
            'zh' (中文), 'en' (英文), 'mixed' (混合), 'unknown' (未知)
        """
        if not text:
            return 'unknown'
        
        # 采样前 1000 个字符进行分析
        sample = text[:1000]
        
        # 中文字符检测（CJK Unified Ideographs）
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', sample))
        
        # 英文字母检测
        english_chars = len(re.findall(r'[a-zA-Z]', sample))
        
        # 计算比例
        total_chars = len(sample)
        if total_chars == 0:
            return 'unknown'
        
        chinese_ratio = chinese_chars / total_chars
        english_ratio = english_chars / total_chars
        
        # 判断逻辑
        if chinese_ratio > 0.3 and english_ratio < 0.1:
            return 'zh'
        elif english_ratio > 0.3 and chinese_ratio < 0.1:
            return 'en'
        elif chinese_ratio > 0.1 and english_ratio > 0.1:
            return 'mixed'
        else:
            return 'unknown'
    
    def _apply_language_specific_rules(self, content: str, language: str) -> str:
        """根据语言应用特定的清洗规则
        
        Args:
            content: 待清洗内容
            language: 语言类型 ('zh', 'en', 'mixed')
        
        Returns:
            清洗后的内容
        """
        result = content
        
        if language == 'zh':
            # 中文特有规则：移除中文标点符号周围的多余空格（中文标点后不应有空格）
            # 使用 Unicode 转义：\u3001=、 \u3002=。 \uff0c=， \uff01=！
            # 先处理“空格 + 标点”：移除标点前的空格
            result = re.sub(r'\s+([\u3001\u3002\uff0c\uff01\uff1a\uff1b\uff08\uff09\u3010\u3011])', r'\1', result)
            # 再处理“标点 + 空格”：移除标点后的空格
            result = re.sub(r'([\u3001\u3002\uff0c\uff01\uff1a\uff1b\uff08\uff09\u3010\u3011])\s+', r'\1', result)
            # 2. 统一全角/半角标点（可选）
            # result = unicodedata.normalize('NFKC', result)
            
        elif language == 'en':
            # 英文特有规则
            # 1. 保留单词间的单个空格
            result = re.sub(r'\s+', ' ', result)
            # 2. 移除标点前的空格
            result = re.sub(r'\s+([, .!?;:()\[\]"\'])', r'\1', result)
            
        elif language == 'mixed':
            # 混合语言：保守处理
            # 1. 仅移除 ASCII 不可见字符
            result = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', result)
            # 2. 规范化空白
            result = re.sub(r'\s+', ' ', result)
        
        return result.strip()
    
    async def _apply_llm_rule(self, content: str, rule_content: str, aigc_model_id: str) -> str:
        """应用 LLM 模型进行智能清洗
        
        Args:
            content: 原始内容
            rule_content: 清洗规则描述
            aigc_model_id: AI 模型 ID
        
        Returns:
            清洗后的内容
        """
        try:
            # TODO: 实际应该调用 LLM 服务
            # 这里提供一个示例实现
            logger.info(f"使用 LLM 模型 ({aigc_model_id}) 处理规则：{rule_content}")
            
            # 构建 Prompt
            prompt = f"""请根据以下清洗规则处理文本：

清洗规则：{rule_content}

原始文本：
{content[:2000]}  # 限制长度，避免超出 token 限制

请直接返回清洗后的文本，不要添加任何解释。"""
            
            # TODO: 调用实际的 LLM 服务
            # from services.llm_service import LLMService
            # llm_service = LLMService(self.db)
            # response = await llm_service.chat(aigc_model_id, prompt)
            # return response['content']
            
            # 暂时返回原始内容（占位符）
            logger.warning("LLM 服务尚未集成，跳过模型处理")
            return content
            
        except Exception as e:
            logger.error(f"LLM 清洗失败：{str(e)}")
            return content  # 失败时返回原始内容
    
    def _apply_script_rule(self, content: str, rule_content: str) -> str:
        """应用脚本规则进行清洗"""
        result = content
        
        # 1. Unicode 规范化（NFKC）- 全角转半角，统一字符表示
        if "Unicode" in rule_content or "规范化" in rule_content or "NFKC" in rule_content:
            result = unicodedata.normalize('NFKC', result)
        
        # 2. ASCII 不可见字符清理
        if "ASCII" in rule_content or "不可见字符" in rule_content:
            # 移除 ASCII 0-32 和 127-160
            result = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\xA0]', '', result)
        
        # 3. Emoji 表情清理
        if "Emoji" in rule_content or "emoji" in rule_content or "表情" in rule_content:
            # Emoji Unicode 范围
            emoji_pattern = re.compile(
                "[\U0001F600-\U0001F64F"  # Emoticons
                "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
                "\U0001F680-\U0001F6FF"  # Transport and Map
                "\U0001F1E0-\U0001F1FF"  # Regional Indicator Symbols
                "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
                "\U00002700-\U000027BF"  # Dingbats
                "\U0001FA70-\U0001FAFF"  # Symbols Extended
                "\U0001FAD0-\U0001FAFF"  # Symbols Extended-A
                "]+",
                flags=re.UNICODE
            )
            result = emoji_pattern.sub('', result)
        
        # 4. 空格/空白字符清理
        if "空格" in rule_content or "空白" in rule_content:
            # 将连续空白替换为单个空格
            result = re.sub(r'\s+', ' ', result)
        
        # 5. Unicode 乱码清理
        if "乱码" in rule_content or "unicode" in rule_content.lower():
            # 移除无意义的 Unicode（示例：移除私有区域）
            result = re.sub(r'[\uE000-\uF8FF]', '', result)
        
        # 6. HTML 标签清理
        if "HTML" in rule_content.upper() or "标签" in rule_content:
            # 移除 HTML 标签
            result = re.sub(r'<[^>]+>', '', result)
        
        # 7. Markdown 标记清理
        if "Markdown" in rule_content or "#" in rule_content:
            # 移除 Markdown 标记
            result = re.sub(r'^#{1,6}\s*', '', result, flags=re.MULTILINE)
            result = re.sub(r'\*\*([^*]+)\*\*', r'\1', result)
            result = re.sub(r'_([^_]+)_', r'\1', result)
        
        # 8. QA 符号/无意义符号清理
        if "QA" in rule_content.upper() or "无意义符号" in rule_content:
            # 移除 Q:, A:等标记
            result = re.sub(r'^\s*[QqAa]：?\s*', '', result, flags=re.MULTILINE)
            result = re.sub(r'[、]{2,}', '', result)
        
        return result.strip()

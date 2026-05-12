# -*- coding: utf-8 -*-
"""
common/utils/llm_client.py
公共 LLM 调用封装（OpenAI 兼容接口）

设计原则：
- 统一 OpenAI 兼容接口，支持私有部署（只需替换 base_url）
- 支持流式（chat_stream）和非流式（chat / call_once）两种模式
- 模型配置优先从 MySQL AIModelModel 加载，降级到 settings.llm.*
- 参考 ragflow api/db/services/llm_service.py LLMBundle
- 参考 jusure_AI controller/rag/utils/llm.py call_llm

使用示例：
  from common.utils import LLMClient, build_llm_client, call_llm_once

  # 方式1：已有 model_config dict
  llm = build_llm_client(model_config)
  async for token in llm.chat_stream(messages):
      ...

  # 方式2：按 model_id 从 DB 加载配置（parser-service 等非流式场景）
  result = await call_llm_once(messages, model_id="xxx", tenant_id="yyy")
"""
from typing import Any, AsyncGenerator
import logging

logger = logging.getLogger("llm_client")


class LLMClient:
    """OpenAI 兼容的 LLM 客户端"""

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        api_key: str = "",
        base_url: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _get_client(self):
        """创建 AsyncOpenAI 客户端（延迟导入，避免启动时强依赖）"""
        try:
            import openai
            from common.config import settings

            return openai.AsyncOpenAI(
                api_key=self.api_key or settings.llm.api_key or "sk-dummy", base_url=self.base_url or settings.llm.base_url or "https://api.openai.com/v1", )
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    async def chat(
        self, messages: list[dict[str, str]], temperature: float | None = None, max_tokens: int | None = None, ) -> str:
        """
        非流式聊天，返回完整 answer 字符串。
        参考 ragflow LLMBundle.chat(sys, hist, gen_conf)
        """
        client = self._get_client()
        resp = await client.chat.completions.create(
            model=self.model_name, messages=messages, temperature=temperature if temperature is not None else self.temperature, max_tokens=max_tokens if max_tokens is not None else self.max_tokens, stream=False, )
        return resp.choices[0].message.content or ""

    async def chat_stream(
        self, messages: list[dict[str, str]], temperature: float | None = None, max_tokens: int | None = None, ) -> AsyncGenerator[str, None]:
        """
        流式聊天，逐 token yield delta 内容。
        参考 ragflow async_chat_streamly / SSE 推送逻辑
        """
        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                model=self.model_name, messages=messages, temperature=temperature if temperature is not None else self.temperature, max_tokens=max_tokens if max_tokens is not None else self.max_tokens, stream=True, )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"LLMClient.chat_stream error: {e}")
            yield f"[ERROR] {e}"

def build_llm_client(model_config: dict[str, Any]) -> LLMClient:
    """
    根据模型配置字典构建 LLMClient。
    model_config 通常来自 MySQL AIModelModel.to_dict()。
    若 model_config 为空则使用全局默认配置（settings.llm.*）。
    """
    from common.config import settings

    return LLMClient(
        model_name=model_config.get("model_name") or settings.llm.default_llm_model or "gpt-4o-mini", api_key=model_config.get("api_key"), base_url=model_config.get("base_url"), temperature=model_config.get("temperature", 0.1), max_tokens=model_config.get("max_tokens", 4096), )

async def load_model_config(model_id: str, tenant_id: str) -> dict[str, Any]:
    """
    按 model_id + tenant_id 从 MySQL AIModelModel 加载模型配置。
    返回 dict，找不到时返回空 {}（调用方应降级到默认配置）。
    """
    try:
        from sqlalchemy import select, and_
        from common.models import db_manager, AIModelModel

        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.id == model_id, AIModelModel.tenant_id == tenant_id, AIModelModel.status != "-1", )
            )
            m = (await session.execute(stmt)).scalar_one_or_none()
            return m.to_dict() if m else {}
    except Exception as e:
        logger.warning(f"load_model_config error (model_id={model_id}): {e}")
        return {}

async def call_llm_once(
    messages: list[dict[str, str]], model_id: str | None = None, tenant_id: str = "", temperature: float | None = None, max_tokens: int | None = None, ) -> str:
    """
    非流式 LLM 调用（工具性场景：摘要提取、QA生成、文件分析等）。

    参数：
      messages   — OpenAI 格式的 messages 列表
      model_id   — 指定模型 ID（从 DB 加载配置），None 则使用默认配置
      tenant_id  — 租户 ID（与 model_id 配合查询）
      temperature / max_tokens — 可覆盖模型默认参数

    对应 jusure_AI controller/rag/utils/llm.py call_llm
    """
    model_config: dict[str, Any] = {}
    if model_id and tenant_id:
        model_config = await load_model_config(model_id, tenant_id)

    llm = build_llm_client(model_config)
    return await llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
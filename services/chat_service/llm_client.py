# -*- coding: utf-8 -*-
"""聊天服务默认大模型客户端。"""
import os
from typing import AsyncGenerator

DEFAULT_LLM_BASE_URL = os.getenv('DEFAULT_LLM_BASE_URL', os.getenv('LLM_BASE_URL', 'http://114.242.210.44:8000/v1'))
DEFAULT_LLM_MODEL_NAME = os.getenv('DEFAULT_LLM_MODEL_NAME', os.getenv('DEFAULT_LLM_MODEL', 'jusure-llm'))
DEFAULT_LLM_API_KEY = os.getenv('LLM_API_KEY', '')

async def stream_chat(messages: list[dict[str, str]]) -> AsyncGenerator[tuple[str, str], None]:
    """调用 OpenAI 兼容聊天接口，并逐 token 向上游返回。"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=DEFAULT_LLM_API_KEY, base_url=DEFAULT_LLM_BASE_URL, timeout=120, )
    stream = await client.chat.completions.create(
        model=DEFAULT_LLM_MODEL_NAME, messages=messages, temperature=0.1, max_tokens=2048, stream=True, )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        content = getattr(delta, "content", None)
        if content:
            yield "content", content
            continue

        # Qwen/DeepSeek 一类模型可能返回推理字段。该内容只作为状态流给前端，
        # 不保存到最终答案，避免把模型推理过程当正式回复展示。
        reasoning = (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "reason_content", None)
            or getattr(delta, "reasoning", None)
        )
        if reasoning:
            yield "reasoning", reasoning
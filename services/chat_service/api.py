# -*- coding: utf-8 -*-
"""chat-service 最小 API。

只保留 knowledge-web 当前使用的 /chat/conversations 接口。
网关注册在 /api/v1 下，因此前端访问路径是：
- POST /api/v1/chat/conversations
- GET  /api/v1/chat/conversations/{conversation_id}/messages
"""
import json
import time
from typing import Any
from fastapi import APIRouter
from fastapi import Query
from fastapi import Header
from fastapi import HTTPException
from fastapi import Depends
from fastapi import Body
from fastapi.responses import StreamingResponse
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from common.auth_context import RequestContext, get_request_context, pick_tenant, pick_user
from common.utils import get_logger
from common.utils.response import api_success
from .core_services import SessionService
from .llm_client import stream_chat
from .retrieval import build_context_prompt, reference_docs, retrieve_knowledge
import uuid

logger = get_logger("chat_api")

# 保留 /ai 空 router，避免 main.py include_router(router) 失败。
router = APIRouter(prefix="/ai", tags=["Chat Service"])
chat_router = APIRouter(prefix="/chat", tags=["Chat Service"])

_session_svc = SessionService()

def build_chat_message(role: Any, content: str) -> ChatCompletionMessageParam:
    """Build an OpenAI-compatible message from persisted chat history."""
    if role == "assistant":
        return ChatCompletionAssistantMessageParam(role="assistant", content=content)
    if role == "system":
        return ChatCompletionSystemMessageParam(role="system", content=content)
    return ChatCompletionUserMessageParam(role="user", content=content)

def sse_event(data: dict[str, Any]) -> bytes:
    """构造标准 SSE message 帧。

    前端使用 fetchEventSource 的 onmessage 消费默认 message 事件。这里不再输出
    `event: chunk` 这类自定义事件名，避免不同代理/调试面板按事件类型分流后，
    前端看到的结构不一致。
    """
    compat = {
        key: data[key]
        for key in ("type", "content", "count", "kb_id", "event", "session_id", "message_id", "id")
        if key in data
    }
    payload = {
        "code": 200, 
        "message": "success", 
        "data": data, # 兼容当前前端 extractStreamContent/extractAssistantReply 的顶层读取逻辑。
        # **compat, 
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

def _build_retrieval_fallback_answer(
    question: str, reference_chunks: list[dict[str, Any]], error: Exception, ) -> str:
    """模型服务不可用时，基于已召回片段给出可读兜底结果。"""
    if not reference_chunks:
        return (
            "当前知识库检索和大模型生成都未能完成。"
            f"模型服务返回错误：{error}。请稍后重试或检查聊天模型服务配置。"
        )

    lines = [
        "已从知识库检索到相关内容，但聊天模型服务暂时不可用，无法生成完整总结。", 
        f"模型服务返回错误：{error}。", "", 
        f"关于“{question}”，可先参考以下片段：", 
    ]
    for index, item in enumerate(reference_chunks[:5], 1):
        content = str(item.get("content") or "").strip()
        if len(content) > 300:
            content = content[:300] + "..."
        if content:
            lines.append(f"{index}. {content}")

    return "\n".join(lines)

@chat_router.post("/conversations")
async def create_conversation(
    body: dict[str, Any] = Body(...), ctx: RequestContext = Depends(get_request_context), ):
    """创建对话。"""
    kb_id = body.get("kb_id")
    title = body.get("title") or "新对话"
    if not kb_id:
        raise HTTPException(status_code=400, detail="kb_id 不能为空")

    session_record = await _session_svc.create_session(
        tenant_id=pick_tenant(ctx), data={
            "app_id": kb_id, "name": title, "user_id": pick_user(ctx), "messages": [], }, )
    return api_success(
        data={
            "conversation_id": session_record.get("session_id") or session_record.get("id"), "title": title, "kb_id": kb_id, "created_at": session_record.get("create_time"), }, message="创建成功", )

@chat_router.get("/conversations")
async def list_conversations(
    page_num: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), ctx: RequestContext = Depends(get_request_context), ):
    """查询对话列表。"""
    result = await _session_svc.list_sessions(
        tenant_id=pick_tenant(ctx), page=page_num, page_size=page_size, user_id=pick_user(ctx) or None, )
    return api_success(data=result)

@chat_router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str, ctx: RequestContext = Depends(get_request_context), ):
    """获取对话消息历史。"""
    session = await _session_svc.get(pick_tenant(ctx), conversation_id)
    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")

    return api_success(
        data={
            "conversation_id": conversation_id, "messages": session.get("messages", []), "question": session.get("question", ""), "answer": session.get("answer", ""), }
    )

@chat_router.post("/conversations/{conversation_id}/messages")
async def send_conversation_message(
    conversation_id: str, body: dict[str, Any] = Body(...), ctx: RequestContext = Depends(get_request_context), ):
    """发送消息，返回 SSE 流。

    前端 `useSendChatMessage.ts` 使用 `fetchEventSource`，要求：
    - POST
    - Content-Type: text/event-stream
    - 每条消息格式为 `data: {...}\n\n`
    """
    content = (body.get("content") or body.get("message") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")

    request_tenant_id = pick_tenant(ctx)
    session = await _session_svc.get(request_tenant_id, conversation_id)
    if not session:
        session = await _session_svc.get_any_tenant(conversation_id)
    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")
    session_tenant_id = session.get("tenant_id") or request_tenant_id

    history = session.get("messages") or []
    kb_id = str(session.get("app_id") or body.get("kb_id") or "").strip()

    async def event_generator():
        answer_parts = []
        reference_chunks = []
        reference_doc_list = []
        session_id = conversation_id
        message_id = str(uuid.uuid4())
        try:
            yield b": stream-start\n\n"
            yield sse_event({"type": "status", "status": "retrieving", "event": "RUN_STARTED", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
            retrieved_chunks = await retrieve_knowledge(session_tenant_id, kb_id, content, top_k=5)
            reference_chunks = [chunk.to_reference() for chunk in retrieved_chunks]
            reference_doc_list = reference_docs(retrieved_chunks)
            yield sse_event(
                {
                    "type": "retrieval", "kb_id": kb_id, "count": len(reference_chunks), "references": reference_chunks, }
            )

            messages: list[ChatCompletionMessageParam] = [
                ChatCompletionSystemMessageParam(role="system", content=build_context_prompt(retrieved_chunks)), *[
                    build_chat_message(item.get("role"), str(item.get("content", "")))
                    for item in history
                    if item.get("content")
                ], ChatCompletionUserMessageParam(role="user", content=content), ]

            thinking_start_flag = False
            thinking_end_flag = False
            thinking_start_time: float | None = None
            text_start_flag = False
            last_heartbeat = time.monotonic()

            def thinking_elapsed() -> float:
                if thinking_start_time is None:
                    return 0
                return round(time.monotonic() - thinking_start_time, 1)

            try:
                async for chunk_type, token in stream_chat(messages):
                    if chunk_type == "content":
                        if not thinking_end_flag:
                            thinking_end_flag = True
                            yield sse_event({"type": "status", "status": "done", "event": "THINKING_END", "time": thinking_elapsed(), "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
                        answer_parts.append(token)
                        if not text_start_flag:
                            text_start_flag = True
                            yield sse_event({"type": "status", "status": "text", "event": "TEXT_START", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
                        yield sse_event({"type": "chunk", "content": token, "event": "TEXT_CONTENT", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
                    else:
                        if not thinking_start_flag:
                            thinking_start_flag = True
                            thinking_start_time = time.monotonic()
                            yield sse_event({"type": "status", "status": "thinking", "event": "THINKING_START", "time": 0, "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
                        yield sse_event({"type": "reasoning", "reasoning_content": token, "event": "THINKING_CONTENT", "time": thinking_elapsed(), "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
                    if time.monotonic() - last_heartbeat > 10:
                        yield b": keep-alive\n\n"
                        last_heartbeat = time.monotonic()
                yield sse_event(
                    {"type": "status", "status": "done", "event": "TEXT_END", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())})
            except Exception as model_error:
                logger.exception("chat model stream failed")
                fallback_answer = _build_retrieval_fallback_answer(
                    content, reference_chunks, model_error, )
                answer_parts.append(fallback_answer)
                yield sse_event(
                    {
                        "type": "done", "content": fallback_answer, "event": "RUN_EEROR", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4())}
                )

            answer = "".join(answer_parts)
            new_history = [
                *history, {"role": "user", "content": content}, {"role": "assistant", "content": answer}, ]
            await _session_svc.update_messages(
                tenant_id=session_tenant_id, session_id=conversation_id, messages=new_history, answer=answer, status="completed", reference_chunks=reference_chunks, reference_docs=reference_doc_list, )
            yield sse_event(
                {"type": "done", "event": "RUN_FINISHED", "session_id": session_id, "message_id": message_id, "id": str(uuid.uuid4()), "references": reference_chunks}, )
        except Exception as e:
            logger.exception("send_conversation_message error")
            yield sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no", "Content-Encoding": "identity", }, )

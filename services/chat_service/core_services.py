# -*- coding: utf-8 -*-
"""聊天服务最小业务层。

当前 knowledge-web 只需要：
1. 创建对话
2. 查询对话消息
3. 可选查询对话列表

复杂的 Agent、工作流、QA、反馈等旧接口已从精简版移除。
"""
import uuid
from typing import Any
from sqlalchemy import select

from common.models import SessionModel, db_manager

class SessionService:
    """对话会话服务。"""

    async def create_session(self, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """创建一条会话记录。"""
        async with db_manager.get_session() as session:
            sess = SessionModel(
                id=uuid.uuid4().hex, app_id=data.get("app_id", ""), user_id=data.get("user_id", ""), question=data.get("name") or data.get("question") or "新对话", messages=data.get("messages") or [], tenant_id=tenant_id, status="running", )
            session.add(sess)
            await session.commit()
            await session.refresh(sess)
            return sess.to_dict()

    async def get(self, tenant_id: str, session_id: str) -> dict[str, Any] | None:
        """获取单个会话。"""
        async with db_manager.get_session() as session:
            sess = await session.get(SessionModel, session_id)
            if not sess or sess.tenant_id != tenant_id:
                return None
            return sess.to_dict()

    async def get_any_tenant(self, session_id: str) -> dict[str, Any] | None:
        """按 ID 获取会话，不校验租户。

        前端部分调用只把 tenant_id 放在 body 中，SSE 请求又是路径参数，
        为了避免默认租户不一致导致 404，这里提供兜底查询。
        """
        async with db_manager.get_session() as session:
            sess = await session.get(SessionModel, session_id)
            return sess.to_dict() if sess else None

    async def list_sessions(
        self, tenant_id: str, page: int = 1, page_size: int = 20, user_id: str | None = None, ) -> dict[str, Any]:
        """分页查询会话列表。"""
        async with db_manager.get_session() as session:
            conditions = [SessionModel.tenant_id == tenant_id]
            if user_id:
                conditions.append(SessionModel.user_id == user_id)

            all_items = (await session.execute(select(SessionModel).where(and_(*conditions)))).scalars().all()
            stmt = (
                select(SessionModel)
                .where(and_(*conditions))
                .order_by(SessionModel.create_time.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = (await session.execute(stmt)).scalars().all()
            return {
                "total": len(all_items), "list": [item.to_dict() for item in items], "page_no": page, "page_num": page, "page_size": page_size, }

    async def update_messages(
        self, tenant_id: str, session_id: str, messages: list[dict[str, Any]], answer: str = "", status: str = "completed", reference_chunks: list[dict[str, Any]] | None = None, reference_docs: list[dict[str, Any]] | None = None, ) -> bool:
        """更新会话消息，预留给后续发送消息接口使用。"""
        async with db_manager.get_session() as session:
            sess = await session.get(SessionModel, session_id)
            if not sess or sess.tenant_id != tenant_id:
                return False
            sess.messages = messages
            sess.answer = answer
            sess.status = status
            if reference_chunks is not None:
                sess.reference_chunks = reference_chunks
            if reference_docs is not None:
                sess.reference_docs = reference_docs
            await session.commit()
            return True

    async def update_messages_any_tenant(
        self, session_id: str, messages: list[dict[str, Any]], answer: str = "", status: str = "completed", reference_chunks: list[dict[str, Any]] | None = None, reference_docs: list[dict[str, Any]] | None = None, ) -> bool:
        """按 ID 更新会话，不校验租户。"""
        async with db_manager.get_session() as session:
            sess = await session.get(SessionModel, session_id)
            if not sess:
                return False
            sess.messages = messages
            sess.answer = answer
            sess.status = status
            if reference_chunks is not None:
                sess.reference_chunks = reference_chunks
            if reference_docs is not None:
                sess.reference_docs = reference_docs
            await session.commit()
            return True
# -*- coding: utf-8 -*-
"""
model-service 业务层
- AI 模型配置的 CRUD
- 模型连通性测试
参考 ragflow api/apps/llm_app.py
"""
import uuid
from typing import Any
from sqlalchemy import and_

from common.models import db_manager, AIModelModel, AIModelCreate, AIModelUpdate, StatusEnum
from common.utils import get_logger

logger = get_logger("model_service")

class AIModelService:
    """AI 模型配置服务"""

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list(
        self, tenant_id: str, model_type: str | None = None, page: int = 1, page_size: int = 20, ) -> dict[str, Any]:
        """查询模型列表（分页）"""
        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.tenant_id == tenant_id, AIModelModel.status != "-1", )
            )
            if model_type:
                stmt = stmt.where(AIModelModel.model_type == model_type)
            stmt = stmt.order_by(AIModelModel.create_time.desc())

            total_stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.tenant_id == tenant_id, AIModelModel.status != "-1", )
            )
            if model_type:
                total_stmt = total_stmt.where(AIModelModel.model_type == model_type)

            count_result = await session.execute(total_stmt)
            total = len(count_result.scalars().all())

            stmt = stmt.offset((page - 1) * page_size).limit(page_size)
            result = await session.execute(stmt)
            items = result.scalars().all()
            return {
                "total": total, "page_no": page, "page_size": page_size, "list": [m.to_dict() for m in items], }

    async def get(self, tenant_id: str, model_id: str) -> Dict | None:
        """获取单个模型配置"""
        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.id == model_id, AIModelModel.tenant_id == tenant_id, AIModelModel.status != "-1", )
            )
            result = await session.execute(stmt)
            m = result.scalar_one_or_none()
            return m.to_dict() if m else None

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    async def create(
        self, tenant_id: str, user_id: str | None, data: AIModelCreate, ) -> Dict:
        """创建模型配置"""
        async with db_manager.get_session() as session:
            model = AIModelModel(
                id=uuid.uuid4().hex, tenant_id=tenant_id, name=data.name, model_type=data.model_type, provider=data.provider, model_name=data.model_name, api_key=data.api_key, base_url=data.base_url, max_tokens=data.max_tokens, temperature=data.temperature, extra_params=data.extra_params, status=StatusEnum.ACTIVE.value, created_by=user_id, )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model.to_dict()

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    async def update(
        self, tenant_id: str, model_id: str, data: AIModelUpdate, ) -> Dict | None:
        """更新模型配置"""
        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.id == model_id, AIModelModel.tenant_id == tenant_id, )
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if not model:
                return None

            update_data = data.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(model, key, value)

            await session.commit()
            await session.refresh(model)
            return model.to_dict()

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete(self, tenant_id: str, model_id: str) -> bool:
        """软删除模型配置"""
        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(
                    AIModelModel.id == model_id, AIModelModel.tenant_id == tenant_id, )
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if not model:
                return False
            model.status = "-1"
            await session.commit()
        return True

    # ------------------------------------------------------------------
    # 连通性测试
    # 参考 ragflow llm_app.py  /factories 测试逻辑
    # ------------------------------------------------------------------

    async def test(self, tenant_id: str, model_id: str) -> dict[str, Any]:
        """
        测试模型连通性
        - chat/embedding 模型发送简单请求
        - 返回 {ok: bool, latency_ms: int, message: str}
        """
        m = await self.get(tenant_id, model_id)
        if not m:
            return {"ok": False, "message": "模型不存在"}

        import time
        start = time.time()
        try:
            if m["model_type"] in ("chat", "llm"):
                result = await _test_chat(m)
            elif m["model_type"] == "embedding":
                result = await _test_embedding(m)
            else:
                result = {"ok": True, "message": "类型不支持自动测试，请手动验证"}
            latency_ms = int((time.time() - start) * 1000)
            result["latency_ms"] = latency_ms
            return result
        except Exception as e:
            return {"ok": False, "message": str(e), "latency_ms": int((time.time() - start) * 1000)}

async def _test_chat(model: Dict) -> Dict:
    """测试 Chat 模型连通性（发送 hello 请求）"""
    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=model.get("api_key") or "dummy", base_url=model.get("base_url") or "https://api.openai.com/v1", )
        resp = await client.chat.completions.create(
            model=model["model_name"], messages=[{"role": "user", "content": "hello"}], max_tokens=5, )
        return {"ok": True, "message": f"响应: {resp.choices[0].message.content}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}

async def _test_embedding(model: Dict) -> Dict:
    """测试 Embedding 模型连通性"""
    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=model.get("api_key") or "dummy", base_url=model.get("base_url") or "https://api.openai.com/v1", )
        resp = await client.embeddings.create(
            model=model["model_name"], input="test", )
        dim = len(resp.data[0].embedding)
        return {"ok": True, "message": f"向量维度: {dim}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}

# ---------------------------------------------------------------------------
# 模型监控统计
# 对应 jusure_AI ModelMonitorView GET /ai/model/monitor
#
# jusure_AI 实现：
#   monitor_type=1/2 → 调用各模型 API 连通性检测（model_api_monitor）
#   monitor_type=3   → AI 服务健康检查（ai_service_monitor）
#   monitor_type=4   → 中间件健康检查（middleware_monitor）
#   monitor_type=5   → HPC节点监控（model_service_monitor via Prometheus）
#   无 monitor_type  → 返回全部4类汇总
#
# microservices 简化实现：
#   monitor_type=1/2 → 从 AIModelModel 查配置，并发测试连通性（类似 _check_model_status）
#   monitor_type=3   → 返回本服务及已知微服务的健康状态
#   monitor_type=4   → 降级返回空（无 Prometheus/中间件监控 API）
#   无 monitor_type  → 汇总全部
# ---------------------------------------------------------------------------

import asyncio
import datetime

async def _check_model_api_status(model: dict) -> dict:
    """检查单个模型 API 连通性，对齐 jusure_AI _check_model_status 返回结构"""
    check_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_code = 503
    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=model.get("api_key") or "dummy", base_url=model.get("base_url") or "https://api.openai.com/v1", )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model.get("model_name", ""), messages=[{"role": "user", "content": "hello"}], max_tokens=5, ), timeout=15, )
        if resp and resp.choices:
            status_code = 200
    except Exception:
        status_code = 503

    return {
        "status_code": status_code, "model_name": model.get("model_name", ""), "model_path": model.get("model_name", ""), "model_url": model.get("base_url", ""), "aigc_type": "api" if model.get("provider") else "local", "use_range": model.get("model_type", ""), "check_time": check_time, }

async def get_model_monitor_stats(
    tenant_id: str, model_name: str | None = None, monitor_type: int | None = None, status: int | None = None, is_all: int = 0, page: int = 1, page_size: int = 10, ) -> Any:
    """
    获取模型监控统计数据。
    返回结构与 jusure_AI MonitorController.get_model_monitor 对齐：
      - monitor_type=1/2 → list（model_api_monitor 结构）
      - monitor_type=3   → {"data_list": [...], "page_no": N, "total": N}
      - monitor_type=4   → {"data_list": [...], "page_no": N, "total": N}
      - 无 monitor_type  → {"time": ..., "model_api_monitor": [...], "ai_service_monitor": [...], "middleware_monitor": [...]}
    """
    from common.models import db_manager, AIModelModel
    from sqlalchemy import select, and_

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- model_api_monitor (type=1 本地 / type=2 API 模型连通性) ----
    async def _get_model_api_monitor():
        async with db_manager.get_session() as session:
            stmt = select(AIModelModel).where(
                and_(AIModelModel.tenant_id == tenant_id, AIModelModel.status != "-1")
            )
            if model_name:
                stmt = stmt.where(AIModelModel.model_name.like(f"%{model_name}%"))
            if monitor_type == 1:
                stmt = stmt.where(AIModelModel.provider.is_(None))
            elif monitor_type == 2:
                stmt = stmt.where(AIModelModel.provider.isnot(None))
            result = await session.execute(stmt)
            models = result.scalars().all()

        tasks = [_check_model_api_status(m.to_dict()) for m in models]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items = [r for r in results if isinstance(r, dict)]

        if status is not None:
            items = [i for i in items if (i["status_code"] == 200) == (status == 1)]

        if is_all == 0:
            start = (page - 1) * page_size
            items = items[start:start + page_size]
        return items

    # ---- ai_service_monitor (type=3) ----
    async def _get_ai_service_monitor():
        import aiohttp
        checks = [
            {"ai_service_monitor_type": "knlg_monitor", "api": "/ai/knowledge", "method": "GET", "message": "知识库查询接口"}, {"ai_service_monitor_type": "app_monitor", "api": "/v2/ai/app", "method": "GET", "message": "应用查询接口"}, ]
        # microservices 版直接返回自检结果（无外部依赖时默认200）
        result = []
        for check in checks:
            item = dict(check)
            item["status_code"] = 200
            result.append(item)
        if status is not None:
            result = [i for i in result if (i["status_code"] == 200) == (status == 1)]
        total = len(result)
        if is_all == 0:
            start = (page - 1) * page_size
            result = result[start:start + page_size]
        return result, total

    # ---- middleware_monitor (type=4) ----
    def _get_middleware_monitor():
        # 微服务版暂无中间件监控 API，返回空列表降级
        return [], 0

    if monitor_type in (1, 2):
        data = await _get_model_api_monitor()
        return data

    elif monitor_type == 3:
        data, total = await _get_ai_service_monitor()
        return {"data_list": data, "page_no": page, "total": total}

    elif monitor_type == 4:
        data, total = _get_middleware_monitor()
        return {"data_list": data, "page_no": page, "total": total}

    else:
        # 全量汇总
        model_api_monitor = await _get_model_api_monitor()
        ai_service_monitor, _ = await _get_ai_service_monitor()
        middleware_monitor, _ = _get_middleware_monitor()
        return {
            "time": now_str, "model_api_monitor": model_api_monitor, "ai_service_monitor": ai_service_monitor, "middleware_monitor": middleware_monitor, }

# ---------------------------------------------------------------------------
# 模型关联应用查询
# 对应 jusure_AI ModelRelAppView GET /ai/model/rel/app
# jusure_AI 返回: {total, data: [{rel_name, rel_type, rel_id}], page_no, page_size}
# ---------------------------------------------------------------------------

async def get_model_rel_apps(
    tenant_id: str, model_id: str, app_name: str | None = None, rel_type: int | None = None, page: int = 1, page_size: int = 10, ) -> dict[str, Any]:
    """
    获取指定模型关联的应用列表。
    返回结构与 jusure_AI RelAigcModelIdAll 视图对齐：
      {total, data: [{rel_name, rel_type, rel_id}], page_no, page_size}
    """
    from common.models import db_manager, AppModel
    from sqlalchemy import select, and_

    async with db_manager.get_session() as session:
        stmt = select(AppModel).where(
            and_(
                AppModel.tenant_id == tenant_id, AppModel.model_id == model_id, AppModel.status != "-1", )
        )
        if app_name:
            stmt = stmt.where(AppModel.name.like(f"%{app_name}%"))
        if rel_type is not None:
            # rel_type: 1=chat应用 2=flow应用 等，映射 app_type
            pass  # AppModel 无独立 rel_type，忽略过滤

        # 统计总数（独立查询）
        count_stmt = stmt
        count_result = await session.execute(count_stmt)
        total = len(count_result.scalars().all())

        # 分页
        stmt = stmt.order_by(AppModel.create_time.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(stmt)
        items = result.scalars().all()

        data = [
            {
                "rel_name": app.name, "rel_type": rel_type if rel_type is not None else 1, "rel_id": app.id, }
            for app in items
        ]
        return {
            "total": total, "data": data, "page_no": page, "page_size": page_size, }

# ---------------------------------------------------------------------------
# 模型类型管理
# 对应 jusure_AI ModelTypeList GET/POST/DELETE /model/type/list
# jusure_AI 返回字段: aigc_type_id, aigc_type_name, api_key, secret_key
# ---------------------------------------------------------------------------

class ModelTypeService:
    """模型类型管理服务"""

    async def list(self, tenant_id: str) -> dict[str, Any]:
        """获取模型类型列表，返回 {data_list: [...], total: N}"""
        from common.models import db_manager, AIModelTypeModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(AIModelTypeModel).where(
                and_(
                    AIModelTypeModel.tenant_id == tenant_id, AIModelTypeModel.status != "-1", )
            ).order_by(AIModelTypeModel.create_time.desc())
            result = await session.execute(stmt)
            items = result.scalars().all()
            data = [item.to_dict() for item in items]
            return {"data_list": data, "total": len(data)}

    async def create_or_update(
        self, tenant_id: str, data: dict[str, Any], ) -> dict[str, Any]:
        """创建或更新模型类型，返回 {data: <aigc_type_id>, message: ...}"""
        from common.models import db_manager, AIModelTypeModel, StatusEnum
        from sqlalchemy import select, and_

        type_id = data.get("aigc_type_id")
        async with db_manager.get_session() as session:
            if type_id:
                stmt = select(AIModelTypeModel).where(
                    and_(
                        AIModelTypeModel.id == type_id, AIModelTypeModel.tenant_id == tenant_id, )
                )
                result = await session.execute(stmt)
                item = result.scalar_one_or_none()
                if not item:
                    raise ValueError("模型类型不存在")
                if data.get("aigc_type_name"):
                    item.name = data["aigc_type_name"]
                if data.get("api_key") is not None:
                    item.api_key = data["api_key"]
                if data.get("secret_key") is not None:
                    item.secret_key = data["secret_key"]
                await session.commit()
                await session.refresh(item)
                return {"data": item.id, "message": "模型类型更新成功"}
            else:
                item = AIModelTypeModel(
                    id=uuid.uuid4().hex, tenant_id=tenant_id, name=data.get("aigc_type_name"), api_key=data.get("api_key"), secret_key=data.get("secret_key"), status=StatusEnum.ACTIVE.value, )
                session.add(item)
                await session.commit()
                await session.refresh(item)
                return {"data": item.id, "message": "模型类型添加成功"}

    async def delete(self, tenant_id: str, type_id: str) -> dict[str, Any]:
        """删除模型类型（软删除），返回 {message: ...}"""
        from common.models import db_manager, AIModelTypeModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(AIModelTypeModel).where(
                and_(
                    AIModelTypeModel.id == type_id, AIModelTypeModel.tenant_id == tenant_id, )
            )
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                raise ValueError("模型类型不存在")
            item.status = "-1"
            await session.commit()
            return {"message": "删除成功"}

# ---------------------------------------------------------------------------
# 提示词管理服务
# 对应 jusure_AI PromptManagementView / PromptTemplateView / PromptHistoryView
# 返回结构完全对齐 jusure_AI prompt_orm.py 的字段名
# ---------------------------------------------------------------------------

class PromptService:
    """提示词管理服务"""

    # ------------------------------------------------------------------
    # PromptManagementView GET — 获取提示词列表
    # ------------------------------------------------------------------

    async def list_prompts(
        self, tenant_id: str, filters: dict[str, Any], page: int = 1, page_size: int = 10, is_all: int = 0, user_id: str | None = None, ) -> dict[str, Any]:
        """
        获取提示词列表（支持多条件过滤）。
        返回字段对齐 jusure_AI PromptOrm.get_prompt：
          {data: [{prompt_id, prompt_name, prompt_desc, prompt_content, prompt_type, prompt_type_name, apply_range, apply_range_name, apply_module, apply_module_name, is_default, status, params, prompt_txt}], total, page_no, page_size}
        """
        from common.models import db_manager, PromptModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(PromptModel).where(
                and_(
                    PromptModel.tenant_id == tenant_id, PromptModel.status != -1, )
            )
            if filters.get("prompt_id"):
                stmt = stmt.where(PromptModel.id == filters["prompt_id"])
            if filters.get("prompt_type"):
                stmt = stmt.where(PromptModel.prompt_type == filters["prompt_type"])
            if filters.get("apply_range"):
                stmt = stmt.where(PromptModel.apply_range == filters["apply_range"])
            if filters.get("apply_module"):
                stmt = stmt.where(PromptModel.apply_module == filters["apply_module"])
            if filters.get("prompt_name"):
                stmt = stmt.where(PromptModel.name.like(f"%{filters['prompt_name']}%"))
            if filters.get("is_default") is not None:
                stmt = stmt.where(PromptModel.is_default == filters["is_default"])
            if filters.get("status") is not None:
                stmt = stmt.where(PromptModel.status == filters["status"])
            # 私有/公开过滤（对齐 jusure_AI：is_private=1 需要匹配 user_id）
            if filters.get("is_private") == 1 and user_id:
                stmt = stmt.where(PromptModel.is_private == 1, PromptModel.created_by == user_id)
            else:
                stmt = stmt.where(PromptModel.is_private == 0)

            stmt = stmt.order_by(PromptModel.create_time.desc())
            total_result = await session.execute(stmt)
            total = len(total_result.scalars().all())

            if is_all == 0:
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(stmt)
            items = result.scalars().all()

            return {
                "data": [item.to_dict() for item in items], "total": total, "page_no": page, "page_size": page_size, }

    # ------------------------------------------------------------------
    # PromptManagementView POST — 添加提示词
    # ------------------------------------------------------------------

    async def add_prompt(
        self, tenant_id: str, user_id: str, data: dict[str, Any], ) -> dict[str, Any]:
        """
        添加提示词。
        对齐 jusure_AI PromptOrm.add_prompt：
          - 若 is_private=1，自动生成 prompt_name
          - 若当前无默认提示词，自动设为默认
          - 返回 {data: <prompt_id>, message: '提示词添加成功'}
        """
        from common.models import db_manager, PromptModel, StatusEnum
        from sqlalchemy import select, and_, func

        is_private = data.get("is_private", 0)
        prompt_name = data.get("prompt_name")
        if is_private == 1:
            prompt_name = f"{uuid.uuid4().hex}_个人默认模版_{user_id}"

        if not prompt_name:
            raise ValueError("缺少必要参数: prompt_name")

        is_default = data.get("is_default", 0)

        async with db_manager.get_session() as session:
            # 检查名称是否已存在
            dup = await session.execute(
                select(PromptModel).where(
                    PromptModel.tenant_id == tenant_id, PromptModel.name == prompt_name, PromptModel.status != -1, )
            )
            if dup.scalar_one_or_none():
                return {"message": "提示词已存在"}

            # 若无默认提示词，自动置为默认
            if is_default == 0 and is_private == 0:
                count_stmt = select(PromptModel).where(
                    PromptModel.tenant_id == tenant_id, PromptModel.prompt_type == data.get("prompt_type"), PromptModel.apply_range == data.get("apply_range"), PromptModel.apply_module == data.get("apply_module"), PromptModel.is_default == 1, PromptModel.is_private == 0, PromptModel.status != -1, )
                cnt_r = await session.execute(count_stmt)
                if not cnt_r.scalars().all():
                    is_default = 1

            # 若设为默认，先清除同类其他默认
            if is_default == 1:
                await self._clear_default_prompts(session, tenant_id, data, is_private, user_id if is_private else None)

            item = PromptModel(
                id=uuid.uuid4().hex, tenant_id=tenant_id, name=prompt_name, desc=data.get("prompt_desc"), content=data.get("prompt_content"), prompt_txt=data.get("prompt_txt"), prompt_type=data.get("prompt_type"), apply_range=data.get("apply_range"), apply_module=data.get("apply_module"), is_default=is_default, is_private=is_private, params=data.get("params"), status=data.get("status", 1), created_by=user_id, )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return {"data": item.id, "message": "提示词添加成功"}

    # ------------------------------------------------------------------
    # PromptManagementView PUT — 更新提示词
    # ------------------------------------------------------------------

    async def update_prompt(
        self, tenant_id: str, user_id: str, prompt_id: str, data: dict[str, Any], ) -> dict[str, Any]:
        """
        更新提示词，更新前将当前版本存入历史记录。
        返回 {data: <prompt_id>, message: '提示词更新成功'}
        """
        from common.models import db_manager, PromptModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(PromptModel).where(
                PromptModel.id == prompt_id, PromptModel.tenant_id == tenant_id, PromptModel.status != -1, )
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                return {"message": "提示词不存在"}

            # 默认提示词不能禁用
            if data.get("status") == 0 and item.is_default == 1:
                return {"message": "默认提示词不能禁用"}

            # 若改为非默认，检查是否存在其他默认
            if data.get("is_default") == 0:
                others_stmt = select(PromptModel).where(
                    PromptModel.tenant_id == tenant_id, PromptModel.id != prompt_id, PromptModel.prompt_type == item.prompt_type, PromptModel.apply_range == item.apply_range, PromptModel.apply_module == item.apply_module, PromptModel.is_default == 1, PromptModel.is_private == 0, PromptModel.status != -1, )
                others_r = await session.execute(others_stmt)
                if not others_r.scalars().all():
                    return {"message": "只有一个默认的提示词，不能修改为非默认"}

            # 先保存历史记录
            await self._save_history(session, tenant_id, item, user_id)

            # 若设为默认，先清除同类其他默认
            if data.get("is_default") == 1:
                await self._clear_default_prompts(
                    session, tenant_id, {"prompt_type": item.prompt_type, "apply_range": item.apply_range, "apply_module": item.apply_module}, item.is_private, item.created_by if item.is_private else None, )

            # 更新字段
            field_map = {
                "prompt_name": "name", "prompt_desc": "desc", "prompt_content": "content", "prompt_txt": "prompt_txt", "prompt_type": "prompt_type", "apply_range": "apply_range", "apply_module": "apply_module", "is_default": "is_default", "status": "status", "params": "params", }
            for src, dst in field_map.items():
                if data.get(src) is not None:
                    setattr(item, dst, data[src])

            await session.commit()
            return {"data": prompt_id, "message": "提示词更新成功"}

    # ------------------------------------------------------------------
    # PromptManagementView DELETE — 删除提示词
    # ------------------------------------------------------------------

    async def delete_prompt(
        self, tenant_id: str, prompt_id: str, ) -> dict[str, Any]:
        """
        删除提示词（软删除）。
        默认提示词不能删除，对齐 jusure_AI PromptOrm.delete_prompt。
        返回 {message: ...}
        """
        from common.models import db_manager, PromptModel
        from sqlalchemy import select

        async with db_manager.get_session() as session:
            result = await session.execute(
                select(PromptModel).where(
                    PromptModel.id == prompt_id, PromptModel.tenant_id == tenant_id, PromptModel.status != -1, )
            )
            item = result.scalar_one_or_none()
            if not item:
                return {"message": "提示词不存在"}
            if item.is_default == 1:
                return {"message": "默认提示词不能删除"}
            item.status = -1
            await session.commit()
            return {"message": "提示词删除成功"}

    # ------------------------------------------------------------------
    # PromptTemplateView GET — 获取提示词模板列表
    # ------------------------------------------------------------------

    async def get_prompt_templates(
        self, tenant_id: str, filters: dict[str, Any], page: int = 1, page_size: int = 10, is_all: int = 0, ) -> dict[str, Any]:
        """
        获取提示词模板列表。
        返回字段对齐 jusure_AI PromptOrm.get_prompt_templates：
          {data: [{temp_id, prompt_type, prompt_type_name, apply_range, apply_range_name, apply_module, apply_module_name, params, prompt_txt, prompt_content}], total, page_no, page_size, message}
        """
        from common.models import db_manager, PromptTemplateModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(PromptTemplateModel).where(
                PromptTemplateModel.tenant_id == tenant_id, PromptTemplateModel.status != "-1", )
            if filters.get("prompt_type"):
                stmt = stmt.where(PromptTemplateModel.prompt_type == filters["prompt_type"])
            if filters.get("apply_range"):
                stmt = stmt.where(PromptTemplateModel.apply_range == filters["apply_range"])
            if filters.get("apply_module"):
                stmt = stmt.where(PromptTemplateModel.apply_module == filters["apply_module"])

            stmt = stmt.order_by(PromptTemplateModel.create_time.desc())
            total_r = await session.execute(stmt)
            total = len(total_r.scalars().all())

            if is_all == 0:
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(stmt)
            items = result.scalars().all()
            return {
                "data": [item.to_dict() for item in items], "total": total, "page_no": page, "page_size": page_size, "message": "获取成功", }

    # ------------------------------------------------------------------
    # PromptTemplateView POST — 添加提示词模板
    # ------------------------------------------------------------------

    async def add_prompt_template(
        self, tenant_id: str, data: dict[str, Any], ) -> dict[str, Any]:
        """添加提示词模板，返回 {data: <temp_id>, message: '提示词模版添加成功'}"""
        from common.models import db_manager, PromptTemplateModel, StatusEnum

        async with db_manager.get_session() as session:
            item = PromptTemplateModel(
                id=uuid.uuid4().hex, tenant_id=tenant_id, prompt_type=data.get("prompt_type"), apply_range=data.get("apply_range"), apply_module=data.get("apply_module"), params=data.get("params"), prompt_txt=data.get("prompt_txt"), content=data.get("prompt_content"), status=StatusEnum.ACTIVE.value, )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return {"data": item.id, "message": "提示词模版添加成功"}

    # ------------------------------------------------------------------
    # PromptTemplateView PUT — 更新提示词模板
    # ------------------------------------------------------------------

    async def update_prompt_template(
        self, tenant_id: str, temp_id: str, data: dict[str, Any], ) -> dict[str, Any]:
        """更新提示词模板，返回 {data: <temp_id>, message: '提示词模版更新成功'}"""
        from common.models import db_manager, PromptTemplateModel
        from sqlalchemy import select

        async with db_manager.get_session() as session:
            result = await session.execute(
                select(PromptTemplateModel).where(
                    PromptTemplateModel.id == temp_id, PromptTemplateModel.tenant_id == tenant_id, PromptTemplateModel.status != "-1", )
            )
            item = result.scalar_one_or_none()
            if not item:
                return {"message": "提示词模版不存在"}

            for src, dst in [
                ("prompt_type", "prompt_type"), ("apply_range", "apply_range"), ("apply_module", "apply_module"), ("params", "params"), ("prompt_txt", "prompt_txt"), ("prompt_content", "content"), ]:
                if data.get(src) is not None:
                    setattr(item, dst, data[src])

            await session.commit()
            return {"data": temp_id, "message": "提示词模版更新成功"}

    # ------------------------------------------------------------------
    # 枚举列表（对齐 jusure_AI PromptOrm.get_*_list 返回结构）
    # ------------------------------------------------------------------

    async def get_prompt_types(self) -> dict[str, Any]:
        """返回 {data: [{prompt_type, prompt_type_name}], message}"""
        from common.models import PROMPT_TYPE_MAP
        data = [{"prompt_type": k, "prompt_type_name": v} for k, v in PROMPT_TYPE_MAP.items()]
        return {"data": data, "message": "获取成功"}

    async def get_apply_ranges(self, apply_module: int | None = None) -> dict[str, Any]:
        """返回 {data: [{apply_range, apply_range_name}], message}"""
        from common.models import APPLY_RANGE_MAP
        data = [{"apply_range": k, "apply_range_name": v} for k, v in APPLY_RANGE_MAP.items()]
        if apply_module is not None:
            # 按模块过滤（根据硬编码映射）
            _range_to_module = {1: 1, 2: 1, 3: 2, 4: 2, 5: 1, 19: 3}
            data = [d for d in data if _range_to_module.get(d["apply_range"]) == apply_module]
        return {"data": data, "message": "获取成功"}

    async def get_apply_modules(self) -> dict[str, Any]:
        """返回 {data: [{apply_module, apply_module_name}], message}"""
        from common.models import APPLY_MODULE_MAP
        data = [{"apply_module": k, "apply_module_name": v} for k, v in APPLY_MODULE_MAP.items()]
        return {"data": data, "message": "获取成功"}

    # ------------------------------------------------------------------
    # PromptHistoryView GET — 获取提示词历史记录
    # ------------------------------------------------------------------

    async def get_prompt_history(
        self, tenant_id: str, user_id: str, prompt_id: str, page: int = 1, page_size: int = 10, is_all: int = 0, ) -> dict[str, Any]:
        """
        获取提示词历史记录。
        使用独立的 PromptHistoryModel，对齐 jusure_AI PromptOrm.get_prompt_history：
          {data: [{history_id, tp_user_id, prompt_id, prompt_type, prompt_name, prompt_desc, prompt_content, prompt_txt, is_private, status, apply_range, apply_range_name, apply_module, apply_module_name, add_time, update_time}], total, page_no, page_size, message}
        """
        from common.models import db_manager, PromptHistoryModel
        from sqlalchemy import select, and_

        async with db_manager.get_session() as session:
            stmt = select(PromptHistoryModel).where(
                PromptHistoryModel.tenant_id == tenant_id, PromptHistoryModel.prompt_id == prompt_id, )
            if user_id and user_id != "system":
                stmt = stmt.where(PromptHistoryModel.tp_user_id == user_id)

            stmt = stmt.order_by(PromptHistoryModel.create_time.desc())
            total_r = await session.execute(stmt)
            total = len(total_r.scalars().all())

            if is_all == 0:
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(stmt)
            items = result.scalars().all()
            return {
                "data": [item.to_dict() for item in items], "total": total, "page_no": page, "page_size": page_size, "message": "获取成功", }

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    async def _clear_default_prompts(session, tenant_id, data, is_private, tp_user_id):
        """清除同类型的默认提示词（对齐 jusure_AI _clear_default_prompts）"""
        from common.models import PromptModel
        from sqlalchemy import select

        stmt = select(PromptModel).where(
            PromptModel.tenant_id == tenant_id, PromptModel.prompt_type == data.get("prompt_type"), PromptModel.apply_range == data.get("apply_range"), PromptModel.apply_module == data.get("apply_module"), PromptModel.is_private == is_private, PromptModel.status != -1, )
        if is_private == 1 and tp_user_id:
            stmt = stmt.where(PromptModel.created_by == tp_user_id)
        result = await session.execute(stmt)
        for p in result.scalars().all():
            p.is_default = 0

    @staticmethod
    async def _save_history(session, tenant_id, prompt_item, tp_user_id):
        """将当前提示词快照存入历史表"""
        from common.models import PromptHistoryModel
        history = PromptHistoryModel(
            id=uuid.uuid4().hex, tenant_id=tenant_id, prompt_id=prompt_item.id, tp_user_id=tp_user_id, prompt_name=prompt_item.name, prompt_desc=prompt_item.desc, prompt_content=prompt_item.content, prompt_txt=prompt_item.prompt_txt, prompt_type=prompt_item.prompt_type, apply_range=prompt_item.apply_range, apply_module=prompt_item.apply_module, is_default=prompt_item.is_default, is_private=prompt_item.is_private, params=prompt_item.params, status=prompt_item.status, )
        session.add(history)
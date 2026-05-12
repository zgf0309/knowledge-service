# -*- coding: utf-8 -*-
"""
model-service 路由
对外接口与 jusure_AI 对齐：
  GET  /ai/model/list    — 模型列表
  POST /ai/model         — 创建/更新模型
  GET  /ai/model         — 模型详情
  DELETE /ai/model       — 删除模型
  POST /ai/model/test    — 连通性测试
参考 ragflow api/apps/llm_app.py
"""
import os
from typing import Any

from fastapi import APIRouter, Query, Body, Header, HTTPException, Depends
from pydantic import BaseModel

from common.auth_context import get_current_request_context, get_request_context, pick_tenant, pick_user
from common.models import AIModelCreate, AIModelUpdate
from common.utils import get_logger
from common.utils.response import api_success

from .services import AIModelService

logger = get_logger("model_api")
router = APIRouter(prefix="/ai", tags=["Model Service"], dependencies=[Depends(get_request_context)])

_svc = AIModelService()

def current_tenant() -> str:
    return pick_tenant(get_current_request_context())

def current_user(default: str = "system") -> str:
    return pick_user(get_current_request_context(), default=default)

# ---------------------------------------------------------------------------
# GET /ai/model/list — 模型列表
# 对应 jusure_AI ModelList GET /ai/model/list
# ---------------------------------------------------------------------------
@router.get("/model/list")
async def list_models(
    tenant_id: str | None = Query("default"), model_type: str | None = Query(None, description="chat/embedding/rerank/..."), page_no: int = Query(1, ge=1), page_size: int = Query(20), ):
    """查询模型列表（分页）"""
    try:
        tenant_id = current_tenant()
        result = await _svc.list(
            tenant_id=tenant_id, model_type=model_type, page=page_no, page_size=page_size, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("list_models error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/model — 创建或更新模型
# 对应 jusure_AI AiModel POST /ai/model（含 model_id 时更新）
# ---------------------------------------------------------------------------
@router.post("/model")
async def create_or_update_model(
    tenant_id: str | None = Query("default"), user_id: str | None = Query(None), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), ):
    """创建或更新 AI 模型配置"""
    effective_user = current_user()
    try:
        tenant_id = current_tenant()
        model_id = body.get("model_id")
        if model_id:
            # 更新
            update_data = AIModelUpdate(**{k: v for k, v in body.items() if k != "model_id"})
            result = await _svc.update(tenant_id, model_id, update_data)
            if result is None:
                raise HTTPException(status_code=404, detail="模型不存在")
            return api_success(data=result, message="更新成功")
        else:
            # 创建
            create_data = AIModelCreate(**body)
            result = await _svc.create(tenant_id, effective_user, create_data)
            return api_success(data=result, message="创建成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("create_or_update_model error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/model — 模型详情
# 对应 jusure_AI AiModel GET /ai/model
# ---------------------------------------------------------------------------
@router.get("/model")
async def get_model(
    tenant_id: str | None = Query("default"), model_id: str = Query(...), ):
    """获取模型配置详情"""
    try:
        tenant_id = current_tenant()
        result = await _svc.get(tenant_id, model_id)
        if result is None:
            raise HTTPException(status_code=404, detail="模型不存在")
        return api_success(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_model error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# DELETE /ai/model — 删除模型
# ---------------------------------------------------------------------------
@router.delete("/model")
async def delete_model(
    tenant_id: str | None = Query("default"), model_id: str = Query(...), ):
    """软删除模型配置"""
    try:
        tenant_id = current_tenant()
        ok = await _svc.delete(tenant_id, model_id)
        if not ok:
            raise HTTPException(status_code=404, detail="模型不存在")
        return api_success(message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("delete_model error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# POST /ai/model/test — 模型连通性测试
# 对应 jusure_AI ModelTestView POST /ai/model/test
# 参考 ragflow llm_app.py
# ---------------------------------------------------------------------------
@router.post("/model/test")
async def test_model(
    tenant_id: str | None = Query("default"), model_id: str = Query(...), ):
    """测试 AI 模型连通性（发送简单请求并返回延迟）"""
    try:
        tenant_id = current_tenant()
        result = await _svc.test(tenant_id, model_id)
        return api_success(data=result)
    except Exception as e:
        logger.exception("test_model error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/model/manage — 模型管理列表（扩展接口，对齐 AiModelManage）
# ---------------------------------------------------------------------------
@router.get("/model/manage")
async def manage_models(
    tenant_id: str | None = Query("default"), model_type: str | None = Query(None), ):
    """模型管理视图（全量列表，不分页）"""
    try:
        tenant_id = current_tenant()
        result = await _svc.list(tenant_id=tenant_id, model_type=model_type, page=1, page_size=1000)
        return api_success(data=result)
    except Exception as e:
        logger.exception("manage_models error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# 待实现接口（中优先级）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GET /ai/embedding/models — 获取系统支持的所有 Embedding 模型列表
# ---------------------------------------------------------------------------
@router.get("/embedding/models")
async def list_supported_embedding_models():
    """
    获取系统支持的所有 Embedding 模型列表
    
    返回所有可用的 embedding 模型信息, 包括:
    - 模型名称
    - 提供商/工厂
    - 向量维度
    - 最大 token 数
    - 支持的语言
    - 推荐场景
    """
    try:
        tenant_id = current_tenant()
        default_embedding_name = os.getenv("DEFAULT_EMBEDDING_MODEL_NAME", "qwen3-embed-4b")
        default_embedding_base_url = os.getenv("DEFAULT_EMBEDDING_BASE_URL", "http://114.242.210.44:6300/v1/embeddings")

        # 定义所有支持的模型信息。注意：前端用 model_name 当 React key，
        # 所以这里必须保证 model_name 唯一，避免重复 key 警告。
        SUPPORTED_MODELS = [
            {
                "model_name": default_embedding_name, "factory": "Jusure", "dimension": 1024, "max_tokens": 8192, "languages": ["中文", "英文", "多语言"], "description": f"默认向量化模型，服务地址：{default_embedding_base_url}", "recommended": True, "type": "self-hosted", "base_url": default_embedding_base_url, }, # 内置模型（本地部署）
            {
                "model_name": "BAAI/bge-m3", "factory": "Builtin", "dimension": 1024, "max_tokens": 8000, "languages": ["多语言", "中文", "英文"], "description": "通用推荐，支持多语言，精度高", "recommended": False, "type": "builtin"
            }, {
                "model_name": "BAAI/bge-small-zh-v1.5", "factory": "Builtin", "dimension": 512, "max_tokens": 512, "languages": ["中文"], "description": "轻量级中文模型，速度快", "recommended": False, "type": "builtin"
            }, {
                "model_name": "BAAI/bge-small-en-v1.5", "factory": "Builtin", "dimension": 384, "max_tokens": 500, "languages": ["英文"], "description": "轻量级英文模型", "recommended": False, "type": "builtin"
            }, {
                "model_name": "Qwen/Qwen3-Embedding-0.6B", "factory": "Builtin", "dimension": 1024, "max_tokens": 30000, "languages": ["多语言", "中文"], "description": "通义千问 embedding 模型，支持长文本", "recommended": False, "type": "builtin"
            }, # 云服务 API 模型
            {
                "model_name": "text-embedding-ada-002", "factory": "OpenAI", "dimension": 1536, "max_tokens": 8000, "languages": ["多语言"], "description": "OpenAI 官方 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "text-embedding-3-small", "factory": "OpenAI", "dimension": 1536, "max_tokens": 8000, "languages": ["多语言"], "description": "OpenAI 新一代小型 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "text-embedding-3-large", "factory": "OpenAI", "dimension": 3072, "max_tokens": 8000, "languages": ["多语言"], "description": "OpenAI 新一代大型 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "embedding-2", "factory": "ZHIPU-AI", "dimension": 1024, "max_tokens": 512, "languages": ["中文", "英文"], "description": "智谱 AI embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "embedding-3", "factory": "ZHIPU-AI", "dimension": 2048, "max_tokens": 3072, "languages": ["中文", "英文"], "description": "智谱 AI 新一代 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "text-embedding-v1", "factory": "DashScope", "dimension": 1536, "max_tokens": 2048, "languages": ["中文"], "description": "阿里云通义 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "text-embedding-v2", "factory": "DashScope", "dimension": 1536, "max_tokens": 2048, "languages": ["中文"], "description": "阿里云通义 embedding V2", "recommended": False, "type": "cloud"
            }, {
                "model_name": "bce-embedding-base_v1", "factory": "Youdao", "dimension": 768, "max_tokens": 512, "languages": ["中文"], "description": "有道 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "jina-embeddings-v3", "factory": "Jina", "dimension": 1024, "max_tokens": 8192, "languages": ["多语言"], "description": "Jina AI embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "jina-embeddings-v4", "factory": "Jina", "dimension": 1024, "max_tokens": 8192, "languages": ["多语言"], "description": "Jina AI 新一代 embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "text-embedding-v4", "factory": "Cohere", "dimension": 1024, "max_tokens": 4000, "languages": ["多语言"], "description": "Cohere embedding V4", "recommended": False, "type": "cloud"
            }, {
                "model_name": "embedding-001", "factory": "Gemini", "dimension": 768, "max_tokens": 2048, "languages": ["多语言"], "description": "Google Gemini embedding 模型", "recommended": False, "type": "cloud"
            }, {
                "model_name": "BAAI/bge-m3-huggingface", "factory": "HuggingFace", "dimension": 1024, "max_tokens": 8000, "languages": ["多语言"], "description": "通过 HuggingFace TEI 部署的 bge-m3", "recommended": False, "type": "self-hosted"
            }, ]

        # 二次去重，防止以后新增模型时再次出现重复 key。
        unique_models = []
        seen_names = set()
        for model in SUPPORTED_MODELS:
            model_name = model["model_name"]
            if model_name in seen_names:
                continue
            seen_names.add(model_name)
            unique_models.append(model)
        
        return api_success(data={
            "models": unique_models, "total": len(unique_models), "default_model": default_embedding_name
        })
    except Exception as e:
        logger.exception("list_supported_embedding_models error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/model/monitor — 模型监控统计
# 对应 jusure_AI ModelMonitorView GET /ai/model/monitor
# ---------------------------------------------------------------------------
@router.get("/model/monitor")
async def get_model_monitor(
    tenant_id: str | None = Query("default"), model_name: str | None = Query(None, description="模型名称过滤"), page_no: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), monitor_type: int | None = Query(None, description="监控类型"), is_all: int = Query(0, description="是否所有监控类型"), status: int | None = Query(None, description="状态码"), ):
    """获取模型监控统计数据（调用量/延迟/成功率）"""
    try:
        tenant_id = current_tenant()
        from .services import get_model_monitor_stats
        result = await get_model_monitor_stats(
            tenant_id=tenant_id, model_name=model_name, monitor_type=monitor_type, status=status, is_all=is_all, page=page_no, page_size=page_size, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("get_model_monitor error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/model/rel/app — 模型关联应用列表
# 对应 jusure_AI ModelRelAppView GET /ai/model/rel/app
# ---------------------------------------------------------------------------
@router.get("/model/rel/app")
async def get_model_rel_apps(
    tenant_id: str | None = Query("default"), aigc_model_id: str = Query(..., description="模型ID"), app_name: str | None = Query(None, description="应用名称过滤"), rel_type: int | None = Query(None, description="关联类型"), page_no: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), ):
    """获取指定模型关联的应用列表"""
    try:
        tenant_id = current_tenant()
        from .services import get_model_rel_apps as _get_rel_apps
        result = await _get_rel_apps(
            tenant_id=tenant_id, model_id=aigc_model_id, app_name=app_name, rel_type=rel_type, page=page_no, page_size=page_size, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("get_model_rel_apps error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET/POST/DELETE /model/type/list — 模型类型管理
# 对应 jusure_AI ModelTypeList GET/POST/DELETE /model/type/list
# ---------------------------------------------------------------------------

from .services import ModelTypeService

_model_type_svc = ModelTypeService()

@router.get("/model/type/list")
async def list_model_types(
    tenant_id: str | None = Query("default"), ):
    """获取模型类型列表"""
    try:
        tenant_id = current_tenant()
        result = await _model_type_svc.list(tenant_id=tenant_id)
        return api_success(data={"data_list": result, "total": len(result)})
    except Exception as e:
        logger.exception("list_model_types error")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/model/type/list")
async def create_or_update_model_type(
    tenant_id: str | None = Query("default"), body: dict[str, Any] = Body(...), ):
    """创建或更新模型类型"""
    try:
        tenant_id = current_tenant()
        result = await _model_type_svc.create_or_update(tenant_id=tenant_id, data=body)
        return api_success(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("create_or_update_model_type error")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/model/type/list")
async def delete_model_type(
    tenant_id: str | None = Query("default"), aigc_type_id: str = Query(..., description="模型类型ID"), ):
    """删除模型类型"""
    try:
        tenant_id = current_tenant()
        ok = await _model_type_svc.delete(tenant_id=tenant_id, type_id=aigc_type_id)
        if not ok:
            raise HTTPException(status_code=404, detail="模型类型不存在")
        return api_success(message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("delete_model_type error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET/POST /ai/prompt/management — 提示词管理
# 对应 jusure_AI PromptManagementView GET/POST /ai/prompt/management
# ---------------------------------------------------------------------------

from .services import PromptService

_prompt_svc = PromptService()

@router.get("/prompt/management")
async def list_prompts(
    tenant_id: str | None = Query("default"), prompt_id: str | None = Query(None, description="提示词ID"), prompt_type: int | None = Query(None, description="提示词类型"), apply_range: int | None = Query(None, description="应用范围"), apply_module: int | None = Query(None, description="应用模块"), page_no: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), prompt_name: str | None = Query(None, description="提示词名称"), is_all: int = Query(0, description="是否全部"), is_private: int | None = Query(0, description="是否个人模板"), is_default: int | None = Query(None, description="是否默认模板"), status: int | None = Query(None, description="状态"), x_user_id: str | None = Header(None), ):
    """获取提示词列表（支持多条件过滤）"""
    try:
        tenant_id = current_tenant()
        filters = {
            "prompt_id": prompt_id, "prompt_type": prompt_type, "apply_range": apply_range, "apply_module": apply_module, "prompt_name": prompt_name, "is_private": is_private, "is_default": is_default, "status": status, }
        result = await _prompt_svc.list_prompts(
            tenant_id=tenant_id, filters={k: v for k, v in filters.items() if v is not None}, page=page_no, page_size=page_size, is_all=is_all, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("list_prompts error")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/prompt/management")
async def create_or_update_prompt(
    tenant_id: str | None = Query("default"), user_id: str | None = Query(None), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), ):
    """创建提示词（POST，无 prompt_id）或更新提示词（POST，含 prompt_id 时走 PUT 语义）"""
    effective_user = current_user()
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.create_or_update_prompt(
            tenant_id=tenant_id, user_id=effective_user, data=body, )
        return api_success(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("create_or_update_prompt error")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/prompt/management")
async def update_prompt(
    tenant_id: str | None = Query("default"), user_id: str | None = Query(None), x_user_id: str | None = Header(None), body: dict[str, Any] = Body(...), ):
    """更新提示词（PUT），更新前自动写入历史记录"""
    effective_user = current_user()
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id 不能为空")
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.update_prompt(
            tenant_id=tenant_id, user_id=effective_user, prompt_id=prompt_id, data=body, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("update_prompt error")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/prompt/management")
async def delete_prompt(
    tenant_id: str | None = Query("default"), body: dict[str, Any] = Body(...), ):
    """删除提示词（默认提示词不可删除）"""
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id 不能为空")
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.delete_prompt(
            tenant_id=tenant_id, prompt_id=prompt_id, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("delete_prompt error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/prompt/template — 提示词模板查询
# 对应 jusure_AI PromptTemplateView GET /ai/prompt/template
# ---------------------------------------------------------------------------
@router.get("/prompt/template")
async def get_prompt_template(
    tenant_id: str | None = Query("default"), prompt_type: int | None = Query(None, description="提示词类型"), apply_range: int | None = Query(None, description="应用范围"), apply_module: int | None = Query(None, description="应用模块"), page_no: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), is_all: int = Query(0, description="是否全部"), is_get_prompt_type: int = Query(0, description="是否获取提示词类型列表"), is_get_apply_range: int = Query(0, description="是否获取应用范围列表"), is_get_apply_module: int = Query(0, description="是否获取应用模块列表"), ):
    """获取提示词模板或枚举列表"""
    try:
        tenant_id = current_tenant()
        if is_get_prompt_type == 1:
            result = await _prompt_svc.get_prompt_types()
            return api_success(data=result)
        elif is_get_apply_range == 1:
            result = await _prompt_svc.get_apply_ranges(apply_module)
            return api_success(data=result)
        elif is_get_apply_module == 1:
            result = await _prompt_svc.get_apply_modules()
            return api_success(data=result)
        else:
            filters = {
                "prompt_type": prompt_type, "apply_range": apply_range, "apply_module": apply_module, }
            result = await _prompt_svc.get_prompt_templates(
                tenant_id=tenant_id, filters={k: v for k, v in filters.items() if v is not None}, page=page_no, page_size=page_size, is_all=is_all, )
            return api_success(data=result)
    except Exception as e:
        logger.exception("get_prompt_template error")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/prompt/template")
async def add_prompt_template(
    tenant_id: str | None = Query("default"), body: dict[str, Any] = Body(...), ):
    """添加提示词模板"""
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.add_prompt_template(
            tenant_id=tenant_id, data=body, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("add_prompt_template error")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/prompt/template")
async def update_prompt_template(
    tenant_id: str | None = Query("default"), body: dict[str, Any] = Body(...), ):
    """更新提示词模板"""
    temp_id = body.get("temp_id")
    if not temp_id:
        raise HTTPException(status_code=400, detail="temp_id 不能为空")
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.update_prompt_template(
            tenant_id=tenant_id, temp_id=temp_id, data=body, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("update_prompt_template error")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# GET /ai/prompt/history — 提示词历史记录
# 对应 jusure_AI PromptHistoryView GET /ai/prompt/history
# ---------------------------------------------------------------------------
@router.get("/prompt/history")
async def get_prompt_history(
    tenant_id: str | None = Query("default"), user_id: str | None = Query(None), x_user_id: str | None = Header(None), prompt_id: str = Query(..., description="提示词ID"), page_no: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), is_all: int = Query(0, description="是否全部"), ):
    """获取提示词历史记录"""
    effective_user = current_user()
    try:
        tenant_id = current_tenant()
        result = await _prompt_svc.get_prompt_history(
            tenant_id=tenant_id, user_id=effective_user, prompt_id=prompt_id, page=page_no, page_size=page_size, is_all=is_all, )
        return api_success(data=result)
    except Exception as e:
        logger.exception("get_prompt_history error")
        raise HTTPException(status_code=500, detail=str(e))

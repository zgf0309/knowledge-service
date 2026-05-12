# -*- coding: utf-8 -*-
"""
SSO 单点登录路由
基于 OIDC + PKCE 实现安全的单点登录
"""
import base64
import json
import logging
import os
import uuid
from fastapi import APIRouter, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any

from utils.oidc_client import get_oidc_client, OIDCClient
from middleware.auth import create_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["SSO Authentication"])

class ApiResponse(BaseModel):
    """统一 API 响应格式 - 与微服务标准对齐"""
    code: int = Field(default=0, description="状态码 (0=成功, 非0=失败)")
    message: str = Field(default="success", description="消息")
    data: Any = Field(default=None, description="数据")

def make_response(data: Any = None, code: int = 200, message: str = "success") -> dict:
    """创建统一响应格式 - 使用 HTTP 标准状态码"""
    return {"code": code, "message": message, "data": data}

class SSOUrlData(BaseModel):
    """SSO 授权 URL 数据"""
    authorization_url: str = Field(..., description="OIDC 授权 URL，需要重定向到该地址")
    state: str = Field(..., description="CSRF 防护 state 参数")

class SSOLoginData(BaseModel):
    """SSO 登录数据"""
    access_token: str = Field(..., description="JWT Token")
    token_type: str = Field(default="bearer", description="Token 类型")
    expires_in: int = Field(..., description="过期时间（秒）")
    user_info: dict = Field(..., description="用户信息")

# 用于存储 PKCE code_verifier（生产环境应使用 Redis 等分布式存储）
# 格式: {state: code_verifier}
_pkce_storage: dict = {}

@router.get("/login")
async def sso_login(url: str | None = None, tenant_id: str | None = Query(None, description="租户 ID（可选，不传则从JWT解析）")):
    """
    SSO 登录 - 获取 OIDC 授权 URL

    该接口生成 OIDC 授权 URL，前端需要重定向到该 URL 进行认证。
    认证完成后，OIDC 服务器会重定向到回调地址。

    ## 参数：
    - **url**: 前端登录页面地址，认证成功后会携带 token 重定向到该地址
      例如：`http://localhost:3000/login` 或 `http://localhost:3000/sso/callback`

    ## 流程：
    1. 调用此接口获取 authorization_url（可携带 url 参数）
    2. 前端重定向到 authorization_url
    3. 用户在 OIDC 服务器完成登录
    4. OIDC 服务器重定向到 /api/v1/auth/sso/callback?code=xxx&state=xxx
    5. 后端使用 code 换取 token，然后重定向到前端 url（如果提供了）

    ## 示例：
    ```bash
    # 不带前端 URL（返回 JSON）
    curl "http://localhost:8000/api/v1/auth/sso/login"
    
    # 带前端 URL（回调时重定向到该地址）
    curl "http://localhost:8000/api/v1/auth/sso/login?url=http://localhost:3000/login"
    ```

    ## 响应：
    ```json
    {
      "code": 200, "message": "", "data": {
        "authorization_url": "http://192.168.192.189:38082/admin-api/system/oidc/authorize?client_id=kbase&...", "state": "random_state_string"
      }
    }
    ```
    """
    try:
        # 本地开发模式：不跳外部 OIDC，直接模拟一次 code/state 回调。
        # 这样 knowledge-web 初始化时不会因为无法访问公司 SSO 而 504/跳转失败。
        if os.getenv("LOCAL_SSO_ENABLED", "true").lower() == "true":
            state = uuid.uuid4().hex
            code = "local-dev-code"
            _pkce_storage[state] = {
                "local_dev": True, "frontend_url": url, "tenant_id": tenant_id or "default", }
            separator = "&" if url and "?" in url else "?"
            authorization_url = f"{url or 'http://localhost:8000/knowledge/list'}{separator}code={code}&state={state}"
            return make_response(
                data={
                    "authorization_url": authorization_url, "state": state, }
            )

        client = await get_oidc_client()

        # 如果提供了前端 URL，使用它作为 redirect_uri
        # 这样 OIDC 服务器会直接回调到前端地址
        redirect_uri = url if url else client.redirect_uri

        # 生成授权 URL
        auth_data = await client.get_authorization_url(redirect_uri=redirect_uri)

        # 存储 code_verifier 和前端 URL（用于后续换取 token）
        # 生产环境应该使用 Redis 等分布式存储，并设置过期时间
        _pkce_storage[auth_data["state"]] = {
            "code_verifier": auth_data["code_verifier"], "code_challenge": auth_data["code_challenge"], "frontend_url": url, # 存储前端 URL
            "redirect_uri": redirect_uri, # 存储实际使用的 redirect_uri
            "tenant_id": tenant_id  # 存储租户 ID
        }
        
        # 清理过期的 state（简单实现，生产环境应使用 TTL）
        if len(_pkce_storage) > 1000:
            # 保留最新的 500 个
            states_to_remove = list(_pkce_storage.keys())[:-500]
            for state in states_to_remove:
                del _pkce_storage[state]
        
        logger.info(f"Generated SSO authorization URL for state: {auth_data['state'][:16]}..., frontend_url: {url}")
        
        return make_response(
            data={
                "authorization_url": auth_data["authorization_url"], "state": auth_data["state"]
            }
        )

    except Exception as e:
        logger.error(f"Failed to generate SSO authorization URL: {e}")
        return JSONResponse(
            status_code=500, content=make_response(
                message=f"生成 SSO 授权 URL 失败: {str(e)}", data=None
            )
        )

@router.get("/callback")
async def sso_callback(
    code: str, state: str, error: str | None = None, error_description: str | None = None
):
    """
    SSO 回调接口 - 处理 OIDC 认证回调
    
    该接口可以被 OIDC 服务器回调，也可以被前端直接调用来换取 token。
    
    ## 使用方式：
    
    ### 方式 1：OIDC 直接回调到前端（当登录时提供了 url 参数）
    1. 前端调用 `/api/v1/auth/sso/login?url=http://localhost:3000/callback`
    2. OIDC 授权完成后，直接回调到 `http://localhost:3000/callback?code=xxx&state=yyy`
    3. 前端将 code 和 state 发送给网关换取 token
    
    ### 方式 2：OIDC 回调到网关（当登录时未提供 url 参数）
    1. 前端调用 `/api/v1/auth/sso/login`
    2. OIDC 授权完成后，回调到 `http://localhost:8000/api/v1/auth/sso/callback?code=xxx&state=yyy`
    
    ## 参数：
    - **code**: OIDC 授权码
    - **state**: CSRF 防护 state 参数
    - **error**: 错误码（如果认证失败）
    - **error_description**: 错误描述（如果认证失败）
    
    ## 响应：
    ```json
    {
      "access_token": "jwt_token_here", "token_type": "bearer", "expires_in": 86400, "user_info": {
        "user_id": "user_sub", "username": "user_name", "email": "user@example.com", "role": "user"
      }
    }
    ```
    """
    # 检查 OIDC 返回的错误
    if error:
        logger.error(f"OIDC authentication error: {error} - {error_description}")
        return JSONResponse(
            status_code=400, content={
                "message": f"OIDC 认证失败: {error} - {error_description or '未知错误'}", "data": None
            }
        )
    
    # 验证 state 参数
    if state not in _pkce_storage:
        logger.error(f"Invalid or expired state: {state[:16]}...")
        return JSONResponse(
            status_code=400, content={
                "message": "无效的 state 参数，可能已过期", "data": None
            }
        )
    
    # 获取 code_verifier 和前端 URL
    pkce_data = _pkce_storage.pop(state)
    code_verifier = pkce_data.get("code_verifier")
    frontend_url = pkce_data.get("frontend_url")  # 获取存储的前端 URL
    redirect_uri = pkce_data.get("redirect_uri")  # 获取存储的 redirect_uri
    tenant_id = pkce_data.get("tenant_id", "default")  # 获取存储的租户 ID
    
    try:
        if pkce_data.get("local_dev"):
            local_user = {
                "user_id": "local-dev-user", "userid": "local-dev-user", "username": "local-dev", "name": "本地开发用户", "email": "local-dev@example.com", "role": "admin", "access": "admin", "tenant_id": tenant_id or "default", }
            access_token = create_token(
                user_id=local_user["user_id"], username=local_user["username"], role=local_user["role"], email=local_user["email"], name=local_user["name"], )
            return make_response(
                data={
                    "access_token": access_token, "token_type": "Bearer", "expires_in": 24 * 3600, "refresh_token": "", "id_token": "", "user_info": local_user, }
            )

        client = await get_oidc_client()
        
        # 使用 code 换取 token（传入授权时使用的 redirect_uri）
        logger.info(f"Exchanging authorization code for token with redirect_uri: {redirect_uri}")
        token_response = await client.exchange_code_for_token(code, code_verifier, redirect_uri)
        
        # 检查是否获取到 access_token
        if not token_response.access_token:
            logger.error("OIDC response does not contain access_token")
            return JSONResponse(
                status_code=400, content={
                    "message": "OIDC 服务器返回的响应中缺少 access_token，请检查 OIDC 配置或授权流程", "data": None
                }
            )
        
        # 获取用户信息
        logger.info("Fetching user info...")
        user_info = await client.get_user_info(token_response.access_token)

        # 从 access_token 的 JWT payload 中解析原始字段，原封不动透传给前端
        parts = token_response.access_token.split(".")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        raw_user_info = json.loads(base64.urlsafe_b64decode(payload_b64))

        # 将 roles JSON 字符串解析为列表（芋道框架特殊处理）
        if isinstance(raw_user_info.get("roles"), str):
            try:
                raw_user_info["roles"] = json.loads(raw_user_info["roles"])
            except Exception:
                pass

        # 从 JWT payload 中获取 tenant_id，优先级：payload中的值 > 传入的参数
        jwt_tenant_id = raw_user_info.get("tenant_id")
        final_tenant_id = jwt_tenant_id or tenant_id

        # 注入最终的 tenant_id 到返回信息中
        raw_user_info["tenant_id"] = final_tenant_id

        logger.info(f"SSO login successful for user: {user_info.sub}, username: {user_info.preferred_username}, tenant_id: {final_tenant_id}")

        # 根据 OIDC Token 透传规范，直接返回 OIDC 原始 token，不生成新 JWT
        # 统一返回 JSON 响应（前端可以直接使用，或根据需要进行重定向）
        return make_response(
            data={
                "access_token": token_response.access_token, "token_type": token_response.token_type or "Bearer", "expires_in": token_response.expires_in or 3600, "refresh_token": token_response.refresh_token, "id_token": token_response.id_token, "user_info": raw_user_info
            }
        )

    except ValueError as e:
        logger.error(f"SSO token exchange failed: {e}")
        return JSONResponse(
            status_code=400, content=make_response(
                message=f"Token 换取失败: {str(e)}", data=None
            )
        )
    except Exception as e:
        logger.error(f"SSO callback processing failed: {e}")
        return JSONResponse(
            status_code=500, content=make_response(
                message=f"SSO 登录处理失败: {str(e)}", data=None
            )
        )

@router.get("/callback/redirect")
async def sso_callback_redirect(
    code: str, state: str, error: str | None = None, error_description: str | None = None
):
    """
    SSO 回调接口（重定向版本）- 适用于前端应用
    
    与 /callback 功能相同，但会将 token 作为 URL 参数重定向到前端页面。
    适用于需要前端处理登录结果的场景。
    
    ## 重定向目标：
    成功：`http://localhost:3000/login?token=jwt_token&success=true`
    失败：`http://localhost:3000/login?error=error_message`
    
    ## 配置：
    通过环境变量 `SSO_FRONTEND_URL` 配置前端地址
    """
    import os
    
    frontend_url = os.getenv("SSO_FRONTEND_URL", "http://localhost:3000/login")
    
    # 检查 OIDC 返回的错误
    if error:
        logger.error(f"OIDC authentication error (redirect): {error}")
        redirect_url = f"{frontend_url}?error={error}"
        if error_description:
            redirect_url += f"&error_description={error_description}"
        return RedirectResponse(url=redirect_url)
    
    # 验证 state 参数
    if state not in _pkce_storage:
        logger.error(f"Invalid or expired state (redirect): {state[:16]}...")
        return RedirectResponse(url=f"{frontend_url}?error=invalid_state")
    
    # 获取 code_verifier 和 tenant_id
    pkce_data = _pkce_storage.pop(state)
    code_verifier = pkce_data["code_verifier"]
    tenant_id = pkce_data.get("tenant_id", "default")  # 获取存储的租户 ID
    
    try:
        client = await get_oidc_client()
        
        # 使用 code 换取 token
        token_response = await client.exchange_code_for_token(code, code_verifier)
        
        # 获取用户信息
        user_info = await client.get_user_info(token_response.access_token)

        # 从 access_token 的 JWT payload 中解析原始字段，原封不动透传给前端
        parts = token_response.access_token.split(".")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        raw_user_info = json.loads(base64.urlsafe_b64decode(payload_b64))

        # 将 roles JSON 字符串解析为列表（芋道框架特殊处理）
        if isinstance(raw_user_info.get("roles"), str):
            try:
                raw_user_info["roles"] = json.loads(raw_user_info["roles"])
            except Exception:
                pass

        # 从 JWT payload 中获取 tenant_id，优先级：payload中的值 > 传入的参数
        jwt_tenant_id = raw_user_info.get("tenant_id")
        final_tenant_id = jwt_tenant_id or tenant_id

        # 注入最终的 tenant_id 到返回信息中
        raw_user_info["tenant_id"] = final_tenant_id

        logger.info(f"SSO login successful (redirect) for user: {user_info.sub}, tenant_id: {final_tenant_id}")

        # 根据 OIDC Token 透传规范，直接返回 OIDC 原始 token 和 user_info
        import urllib.parse
        params = {
            "access_token": token_response.access_token, "token_type": token_response.token_type or "Bearer", "success": "true"
        }
        if token_response.expires_in is not None:
            params["expires_in"] = str(token_response.expires_in)
        if token_response.refresh_token:
            params["refresh_token"] = token_response.refresh_token
        if token_response.id_token:
            params["id_token"] = token_response.id_token

        params["user_info"] = json.dumps(raw_user_info, ensure_ascii=False)
        query_string = urllib.parse.urlencode(params)
        redirect_url = f"{frontend_url}?{query_string}"
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"SSO callback redirect failed: {e}")
        return RedirectResponse(url=f"{frontend_url}?error=login_failed&message={str(e)}")

@router.get("/config")
async def get_sso_config():
    """
    获取 SSO 配置信息
    
    用于前端获取 OIDC 配置，以便进行前端直接跳转（可选）
    
    ## 响应：
    ```json
    {
      "enabled": true, "client_id": "kbase", "discovery_url": "http://192.168.192.189:38082/admin-api/system/oidc/.well-known/openid-configuration", "scope": "openid email profile"
    }
    ```
    """
    import os
    
    return make_response(
        data={
            "enabled": os.getenv("SSO_ENABLED", "true").lower() == "true", "client_id": os.getenv("OIDC_CLIENT_ID", "kbase"), "discovery_url": os.getenv(
                "OIDC_DISCOVERY_URL", "http://192.168.192.189:38082/admin-api/system/oidc/.well-known/openid-configuration"
            ), "scope": "openid email profile", "redirect_uri": os.getenv(
                "OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/sso/callback"
            )
        }
    )

@router.get("/logout")
async def sso_logout(
    redirect_url: str | None = Query(None, description="登出后重定向的前端地址"), id_token_hint: str | None = Query(None, description="OIDC 的 id_token（用于 OIDC 登出）")
):
    """
    SSO 登出

    处理 SSO 登出流程，支持本地登出和 OIDC 联合登出。

    ## 登出流程：
    1. 前端清除本地 JWT Token
    2. 调用此接口（可选携带 id_token_hint）
    3. 如果有 OIDC end_session_endpoint，返回 OIDC 登出 URL
    4. 前端重定向到 OIDC 登出页面（如果需要）
    5. OIDC 服务器处理完成后重定向回前端

    ## 参数：
    - **redirect_url**: 登出完成后重定向回前端的地址，例如：`http://localhost:3000/login`
    - **id_token_hint**: OIDC 登录时获取的 id_token，用于 OIDC 单点登出

    ## 响应：
    ```json
    {
      "code": 0, "message": "success", "data": {
        "logout_url": "http://oidc-server/logout?id_token_hint=...&post_logout_redirect_uri=...", "local_logout": true, "oidc_logout_required": true
      }
    }
    ```

    ## 前端集成示例：
    ```javascript
    // 1. 清除本地 token
    localStorage.removeItem('token');

    // 2. 调用登出接口
    const response = await fetch('/api/v1/auth/sso/logout?redirect_url=http://localhost:3000/login');
    const result = await response.json();

    // 3. 如果需要 OIDC 登出，重定向到 OIDC 登出页面
    if (result.data.oidc_logout_required && result.data.logout_url) {
      window.location.href = result.data.logout_url;
    } else {
      // 仅本地登出，直接跳转登录页
      window.location.href = '/login';
    }
    ```
    """
    try:
        client = await get_oidc_client()
        config = await client._load_oidc_config()

        # 检查 OIDC 是否支持 end_session_endpoint
        end_session_endpoint = getattr(config, 'end_session_endpoint', None)

        if end_session_endpoint and redirect_url:
            # 构建 OIDC 登出 URL
            import urllib.parse
            params = {
                "post_logout_redirect_uri": redirect_url
            }
            if id_token_hint:
                params["id_token_hint"] = id_token_hint

            query_string = urllib.parse.urlencode(params)
            logout_url = f"{end_session_endpoint}?{query_string}"

            return make_response(
                data={
                    "logout_url": logout_url,
                    "local_logout": True,
                    "oidc_logout_required": True
                },
                message="请重定向到 OIDC 登出页面完成登出"
            )
        else:
            # 仅本地登出
            return make_response(
                data={
                    "logout_url": None,
                    "local_logout": True,
                    "oidc_logout_required": False
                },
                message="登出成功"
            )

    except Exception as e:
        logger.error(f"SSO logout failed: {e}")
        # 即使出错也返回成功，因为本地 token 已经清除
        return make_response(
            data={
                "logout_url": None,
                "local_logout": True,
                "oidc_logout_required": False
            },
            message="本地登出成功"
        )

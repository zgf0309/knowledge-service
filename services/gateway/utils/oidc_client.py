# -*- coding: utf-8 -*-
"""
OIDC + PKCE 客户端实现
支持自动发现 OIDC 配置，使用 PKCE 流程进行安全认证
"""
import base64
import hashlib
import json
import secrets
import logging
from typing import Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

@dataclass
class OIDCConfig:
    """OIDC 配置数据类"""
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    scopes_supported: list
    response_types_supported: list
    grant_types_supported: list
    code_challenge_methods_supported: list
    end_session_endpoint: str | None = None  # OIDC 登出端点
    revocation_endpoint: str | None = None   # Token 撤销端点

@dataclass
class TokenResponse:
    """Token 响应数据类"""
    access_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    scope: str | None = None

@dataclass
class UserInfo:
    """用户信息数据类"""
    sub: str
    email: str | None = None
    name: str | None = None
    preferred_username: str | None = None
    picture: str | None = None
    groups: list | None = None

class OIDCClient:
    """
    OIDC + PKCE 客户端
    
    功能：
    1. 自动发现 OIDC 配置（/.well-known/openid-configuration）
    2. 生成 PKCE 参数（code_verifier, code_challenge）
    3. 生成授权 URL
    4. 使用 code 换取 token
    5. 获取用户信息
    """
    
    def __init__(
        self, discovery_url: str, client_id: str, redirect_uri: str, scope: str = "openid email profile", timeout: int = 30
    ):
        """
        初始化 OIDC 客户端
        
        Args:
            discovery_url: OIDC 发现端点 URL
            client_id: 客户端 ID
            redirect_uri: 回调地址
            scope: 请求的作用域
            timeout: HTTP 请求超时时间
        """
        self.discovery_url = discovery_url
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.timeout = timeout
        self._config: OIDCConfig | None = None
        self._http_client = httpx.AsyncClient(timeout=timeout)
    
    async def initialize(self) -> None:
        """
        初始化 OIDC 客户端，预加载配置
        在应用启动时调用，将配置缓存到内存中
        """
        if self._config is not None:
            logger.info("OIDC configuration already loaded")
            return
        
        try:
            logger.info(f"Initializing OIDC client, loading configuration from: {self.discovery_url}")
            response = await self._http_client.get(self.discovery_url)
            response.raise_for_status()
            data = response.json()
            
            self._config = OIDCConfig(
                issuer=data.get("issuer", ""), authorization_endpoint=data.get("authorization_endpoint", ""), token_endpoint=data.get("token_endpoint", ""), userinfo_endpoint=data.get("userinfo_endpoint", ""), jwks_uri=data.get("jwks_uri", ""), scopes_supported=data.get("scopes_supported", []), response_types_supported=data.get("response_types_supported", []), grant_types_supported=data.get("grant_types_supported", []), code_challenge_methods_supported=data.get("code_challenge_methods_supported", ["S256"]), end_session_endpoint=data.get("end_session_endpoint"), revocation_endpoint=data.get("revocation_endpoint")
            )
            
            logger.info(f"OIDC client initialized successfully. Token endpoint: {self._config.token_endpoint}")
            
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to OIDC server: {self.discovery_url} - {e}")
            raise ValueError(f"无法连接到 OIDC 服务器，请检查网络连接或 OIDC 服务器状态: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"OIDC server returned error: {e.response.status_code} - {e}")
            raise ValueError(f"OIDC 服务器返回错误 (HTTP {e.response.status_code})，请检查 OIDC 服务是否正常运行: {e}")
        except httpx.HTTPError as e:
            logger.error(f"Failed to load OIDC configuration: {e}")
            raise ValueError(f"无法加载 OIDC 配置: {e}")
        except Exception as e:
            logger.error(f"Unexpected error loading OIDC configuration: {e}")
            raise
    
    async def _load_oidc_config(self) -> OIDCConfig:
        """
        获取 OIDC 配置（从缓存或加载）
        
        Returns:
            OIDCConfig: OIDC 配置对象
        """
        if self._config is None:
            await self.initialize()
        return self._config
    
    @staticmethod
    def generate_pkce_challenge() -> dict[str, str]:
        """
        生成 PKCE 参数
        
        按照 RFC 7636 标准生成 code_verifier 和 code_challenge
        code_verifier 长度必须在 43-128 字符之间
        
        Returns:
            Dict: 包含 code_verifier 和 code_challenge 的字典
        """
        # 生成 32 字节随机数据，base64url 编码后长度为 43 字符
        # 符合 RFC 7636 要求（43-128 字符）
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode('utf-8').rstrip('=')
        
        # 使用 SHA256 生成 code_challenge
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode('utf-8').rstrip('=')
        
        return {
            "code_verifier": code_verifier, "code_challenge": code_challenge, "code_challenge_method": "S256"
        }
    
    async def get_authorization_url(
        self, state: str | None = None, redirect_uri: str | None = None, additional_params: dict[str, str] | None = None
    ) -> dict[str, str]:
        """
        生成 OIDC 授权 URL
        
        Args:
            state: 可选的 state 参数（用于防止 CSRF）
            redirect_uri: 可选的自定义回调地址（默认使用配置的 redirect_uri）
            additional_params: 额外的查询参数
        
        Returns:
            Dict: 包含 authorization_url、state、code_verifier 的字典
        """
        config = await self._load_oidc_config()
        
        # 生成 PKCE 参数
        pkce = self.generate_pkce_challenge()
        
        # 生成 state（如果未提供）
        if state is None:
            state = secrets.token_urlsafe(32)
        
        # 使用传入的 redirect_uri 或默认的 redirect_uri
        effective_redirect_uri = redirect_uri or self.redirect_uri
        
        # 构建授权 URL
        params = {
            "client_id": self.client_id, "response_type": "code", "scope": self.scope, "redirect_uri": effective_redirect_uri, "state": state, "code_challenge": pkce["code_challenge"], "code_challenge_method": pkce["code_challenge_method"]
        }
        
        # 添加额外参数
        if additional_params:
            params.update(additional_params)
        
        # 构建 URL
        import urllib.parse
        query_string = urllib.parse.urlencode(params)
        authorization_url = f"{config.authorization_endpoint}?{query_string}"
        
        logger.info(f"Generated authorization URL for client: {self.client_id}, redirect_uri: {effective_redirect_uri}")
        
        return {
            "authorization_url": authorization_url, "state": state, "code_verifier": pkce["code_verifier"], "code_challenge": pkce["code_challenge"]
        }
    
    async def exchange_code_for_token(
        self, code: str, code_verifier: str, redirect_uri: str | None = None
    ) -> TokenResponse:
        """
        使用授权码换取 Token
        
        Args:
            code: 授权码
            code_verifier: PKCE code_verifier
            redirect_uri: 回调地址（默认为初始化时的 redirect_uri）
        
        Returns:
            TokenResponse: Token 响应
        """
        config = await self._load_oidc_config()
        
        # 使用传入的 redirect_uri 或默认的 redirect_uri
        effective_redirect_uri = redirect_uri or self.redirect_uri
        
        payload = {
            "grant_type": "authorization_code", "client_id": self.client_id, "code": code, "redirect_uri": effective_redirect_uri, "code_verifier": code_verifier
        }
        
        try:
            logger.info(f"Exchanging code for token at: {config.token_endpoint}")
            logger.debug(f"Token request payload: {payload}")
            
            response = await self._http_client.post(
                config.token_endpoint, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            # 记录原始响应内容用于调试
            response_text = response.text
            logger.info(f"Token response status: {response.status_code}")
            logger.info(f"Token response body: {response_text}")
            
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"Token response parsed data: {data}")
            
            token_response = TokenResponse(
                access_token=data.get("access_token"), token_type=data.get("token_type", "Bearer"), expires_in=data.get("expires_in", 3600), refresh_token=data.get("refresh_token"), id_token=data.get("id_token"), scope=data.get("scope")
            )
            
            logger.info("Token exchange successful")
            return token_response
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Token exchange HTTP error: {e.response.status_code}")
            logger.error(f"Error response body: {e.response.text}")
            raise ValueError(f"换取 Token 失败 (HTTP {e.response.status_code}): {e.response.text}")
        except httpx.HTTPError as e:
            logger.error(f"Token exchange failed: {e}")
            raise ValueError(f"换取 Token 失败: {e}")
        except KeyError as e:
            logger.error(f"Missing field in token response: {e}")
            logger.error(f"Response data: {data if 'data' in locals() else 'N/A'}")
            raise ValueError(f"Token 响应格式错误，缺少字段: {e}")
    
    @staticmethod
    def _parse_user_info_from_jwt(access_token: str) -> UserInfo | None:
        """
        直接从 JWT access_token 的 payload 中解析用户信息（无需验证签名）。
        适用于 OIDC 服务器将用户信息嵌入 token 的场景。

        Returns:
            UserInfo 或 None（解析失败时）
        """
        try:
            parts = access_token.split(".")
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            # 补全 base64 padding
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))

            sub = str(payload.get("sub", ""))
            if not sub:
                return None

            # 处理 roles/groups：可能是 JSON 字符串（如芋道框架），也可能是列表
            groups = payload.get("roles") or payload.get("groups")
            if isinstance(groups, str):
                try:
                    groups = json.loads(groups)
                except Exception:
                    groups = [groups] if groups else None

            return UserInfo(
                sub=sub, email=payload.get("email"), name=payload.get("name"), preferred_username=payload.get("preferred_username"), picture=payload.get("picture"), groups=groups, )
        except Exception as e:
            logger.warning(f"Failed to parse user info from JWT payload: {e}")
            return None

    async def get_user_info(self, access_token: str) -> UserInfo:
        """
        获取用户信息。

        优先从 JWT access_token payload 中直接解析（避免再次请求 userinfo 端点），
        若解析失败则回退到调用 userinfo 端点，并兼容芋道框架的包裹式响应格式：
        {"code": 0, "data": {"id": 1, "nickname": "admin", ...}}

        Args:
            access_token: 访问令牌

        Returns:
            UserInfo: 用户信息
        """
        # 优先从 JWT payload 直接解析（标准 OIDC access_token 包含用户信息）
        user_info = self._parse_user_info_from_jwt(access_token)
        if user_info:
            logger.info(f"User info parsed from JWT payload, sub: {user_info.sub}")
            return user_info

        # 回退：调用 userinfo 端点
        config = await self._load_oidc_config()
        try:
            logger.info(f"Fetching user info from userinfo endpoint: {config.userinfo_endpoint}")
            response = await self._http_client.get(
                config.userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            raw = response.json()

            # 兼容芋道框架的包裹格式：{"code": 0, "data": {...}}
            if isinstance(raw.get("data"), dict):
                data = raw["data"]
                logger.info(f"Detected wrapped userinfo response, unwrapping 'data' field")
            else:
                data = raw

            # 字段映射：芋道用 id/nickname/username/mail，标准 OIDC 用 sub/name/preferred_username/email
            sub = str(
                data.get("sub")
                or data.get("id")
                or data.get("userId")
                or ""
            )
            user_info = UserInfo(
                sub=sub, email=data.get("email") or data.get("mail"), name=data.get("name") or data.get("nickname"), preferred_username=data.get("preferred_username") or data.get("username"), picture=data.get("picture") or data.get("avatar"), groups=data.get("groups") or data.get("roles"), )

            logger.info(f"User info retrieved from userinfo endpoint, sub: {user_info.sub}")
            return user_info

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch user info: {e}")
            raise ValueError(f"获取用户信息失败: {e}")
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self._http_client.aclose()

# 全局 OIDC 客户端实例（单例模式）
_oidc_client: OIDCClient | None = None

async def get_oidc_client() -> OIDCClient:
    """
    获取 OIDC 客户端实例（单例）
    
    Returns:
        OIDCClient: OIDC 客户端实例
    """
    global _oidc_client
    if _oidc_client is None:
        import os
        discovery_url = os.getenv(
            "OIDC_DISCOVERY_URL", "http://192.168.192.189:38082/admin-api/system/oidc/.well-known/openid-configuration"
        )
        client_id = os.getenv("OIDC_CLIENT_ID", "kbase")
        redirect_uri = os.getenv(
            "OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/sso/callback"
        )
        
        _oidc_client = OIDCClient(
            discovery_url=discovery_url, client_id=client_id, redirect_uri=redirect_uri
        )
    return _oidc_client

def reset_oidc_client():
    """重置 OIDC 客户端实例（用于测试）"""
    global _oidc_client
    _oidc_client = None
# -*- coding: utf-8 -*-
"""
JWT 认证中间件
验证请求中的 JWT Token，确保只有授权用户可以访问 API
"""
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import HTTPException
import jwt
from datetime import datetime, timedelta
from config.gateway_config import GatewayConfig
import logging

logger = logging.getLogger(__name__)

class AuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件"""
    
    def __init__(self, app):
        super().__init__(app)
        self.config = GatewayConfig()
        auth_cfg = self.config.auth_config
        self.jwt_secret = auth_cfg.get("jwt_secret", "your-secret-key")
        self.jwt_algorithm = auth_cfg.get("jwt_algorithm", "HS256")
        self.exclude_paths = set(auth_cfg.get("exclude_paths", []))
    
    async def dispatch(self, request, call_next):
        # 检查是否需要认证
        path = request.url.path
        
        # 跳过不需要认证的路径
        if any(path.startswith(exclude) for exclude in self.exclude_paths):
            logger.debug(f"跳过认证：{path}")
            return await call_next(request)
        
        # 获取 Authorization header
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            logger.warning(f"缺少认证头：{path}")
            raise HTTPException(
                status_code=401,
                detail="未提供认证信息，请在 Header 中添加 Authorization 字段"
            )
        
        # 解析 Bearer Token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            logger.warning(f"无效的认证格式：{path}")
            raise HTTPException(
                status_code=401,
                detail="认证格式错误，应为：Bearer <token>"
            )
        
        token = parts[1]
        
        # 尝试验证 Token
        payload = await self._verify_token(token, path)
        
        if not payload:
            raise HTTPException(
                status_code=401,
                detail="无效的 Token"
            )
        
        # 提取用户信息并添加到请求头
        user_id = payload.get("sub")
        username = payload.get("username") or payload.get("preferred_username") or payload.get("name")
        role = payload.get("role", "user")
        
        # 将用户信息添加到请求头，传递给下游服务
        request.state.user_id = user_id
        request.state.username = username
        request.state.role = role
        
        logger.debug(f"认证成功：{username} ({role}) - {path}")
        
        return await call_next(request)
    
    async def _verify_token(self, token: str, path: str) -> dict:
        """
        验证 Token，支持多种方式：
        1. Gateway 自己颁发的 JWT Token
        2. OIDC access_token（从 payload 解析，不验证签名）
        """
        # 方式 1：尝试验证 Gateway 自己的 JWT Token
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm]
            )
            logger.debug(f"Gateway JWT 验证成功：{path}")
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning(f"Gateway Token 已过期：{path}")
            raise HTTPException(
                status_code=401,
                detail="Token 已过期，请重新登录"
            )
        except jwt.InvalidTokenError:
            # 不是 Gateway 颁发的 Token，继续尝试其他方式
            pass
        
        # 方式 2：尝试从 OIDC access_token 的 payload 中解析（不验证签名）
        try:
            # OIDC Token 通常是 JWT 格式，直接解析 payload
            parts = token.split(".")
            if len(parts) == 3:
                import base64
                import json
                
                # 解码 payload
                payload_b64 = parts[1]
                # 补全 base64 padding
                payload_b64 += "=" * (4 - len(payload_b64) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                
                # 检查必要的字段
                if payload.get("sub"):
                    logger.debug(f"OIDC Token 解析成功：{path}")
                    return payload
        except Exception as e:
            logger.warning(f"OIDC Token 解析失败：{path} - {e}")
        
        # 所有方式都失败
        logger.warning(f"Token 验证失败：{path}")
        return None

def create_token(
    user_id: str,
    username: str,
    role: str = "user",
    expire_hours: int = 24,
    email: str = "",
    name: str = "",
    picture: str = "",
) -> str:
    """
    创建 JWT Token
    
    Args:
        user_id: 用户 ID
        username: 用户名
        role: 用户角色（admin/user/guest）
        expire_hours: 过期时间（小时）
        email: 用户邮箱
        name: 用户显示名
        picture: 用户头像 URL
    
    Returns:
        JWT Token 字符串
    """
    config = GatewayConfig()
    auth_cfg = config.auth_config
    
    expire = datetime.utcnow() + timedelta(hours=expire_hours)
    
    payload = {
        "sub": user_id,
        "user_id": user_id,   # 冗余字段，方便前端直接读取
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    # 仅在有值时写入可选字段，避免 payload 含无意义空串
    if email:
        payload["email"] = email
    if name:
        payload["name"] = name
    if picture:
        payload["picture"] = picture
    
    token = jwt.encode(
        payload,
        auth_cfg.get("jwt_secret", "your-secret-key"),
        algorithm=auth_cfg.get("jwt_algorithm", "HS256")
    )
    
    return token

def verify_token(token: str) -> dict:
    """
    验证 JWT Token
    
    Args:
        token: JWT Token 字符串
    
    Returns:
        解析后的 payload 字典
    
    Raises:
        jwt.ExpiredSignatureError: Token 已过期
        jwt.InvalidTokenError: Token 无效
    """
    config = GatewayConfig()
    auth_cfg = config.auth_config
    
    payload = jwt.decode(
        token,
        auth_cfg.get("jwt_secret", "your-secret-key"),
        algorithms=[auth_cfg.get("jwt_algorithm", "HS256")]
    )
    
    return payload

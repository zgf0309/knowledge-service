# -*- coding: utf-8 -*-
"""
认证相关 API
提供登录、注册、Token 刷新等功能
"""
from fastapi import APIRouter, HTTPException, Body, Header
from pydantic import BaseModel, Field
from typing import Any
import uuid
from datetime import datetime
from middleware.auth import create_token, verify_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

def make_response(data: Any = None, code: int = 200, message: str = "success") -> dict:
    """创建统一响应格式 - 使用 HTTP 标准状态码"""
    return {"code": code, "message": message, "data": data}

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

class LoginData(BaseModel):
    """登录数据"""
    access_token: str = Field(..., description="JWT Token")
    token_type: str = Field(default="bearer", description="Token 类型")
    expires_in: int = Field(..., description="过期时间（秒）")
    user_info: dict = Field(..., description="用户信息")

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="邮箱")
    password: str = Field(..., description="密码")

@router.post("/login")
async def login(request: LoginRequest):
    """
    用户登录
    
    验证用户名密码，返回 JWT Token
    
    **注意**: 当前为演示实现，实际应连接数据库验证
    """
    # TODO: 连接到数据库验证用户凭证
    # 这里是简化示例
    if request.username == "admin" and request.password == "admin123":
        # 创建 Token
        token = create_token(
            user_id=str(uuid.uuid4()),
            username=request.username,
            role="admin",
            expire_hours=24
        )
        
        return make_response(
            data={
                "access_token": token,
                "token_type": "bearer",
                "expires_in": 24 * 3600,
                "user_info": {
                    "user_id": str(uuid.uuid4()),
                    "username": request.username,
                    "role": "admin",
                    "email": "admin@example.com"
                }
            }
        )
    
    # 其他用户默认拒绝（实际应该查询数据库）
    raise HTTPException(
        status_code=401,
        detail="用户名或密码错误"
    )

@router.post("/register")
async def register(request: RegisterRequest):
    """
    用户注册
    
    创建新用户账户
    
    **注意**: 当前为演示实现，实际应写入数据库
    """
    # TODO: 将用户信息写入数据库
    # 这里只是示例
    
    # 检查用户名是否已存在（实际应该查询数据库）
    if request.username == "admin":
        raise HTTPException(
            status_code=400,
            detail="用户名已被使用"
        )
    
    # 创建用户（实际应该保存到数据库）
    user_id = str(uuid.uuid4())

    return make_response(
        data={
            "user_id": user_id,
            "username": request.username,
            "email": request.email
        },
        message="注册成功"
    )

@router.post("/refresh")
async def refresh_token(token: str = Body(..., embed=True)):
    """
    刷新 Token
    
    使用旧的 JWT Token 换取新的 Token
    """
    try:
        # 验证旧 Token
        payload = verify_token(token)
        
        # 创建新 Token
        new_token = create_token(
            user_id=payload.get("sub"),
            username=payload.get("username"),
            role=payload.get("role", "user"),
            expire_hours=24
        )
        
        return make_response(
            data={
                "access_token": new_token,
                "token_type": "bearer",
                "expires_in": 24 * 3600
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Token 无效：{str(e)}"
        )

@router.get("/verify")
async def verify_authorization(authorization: str | None = Header(None)):
    """
    验证 Token 有效性
    
    用于前端检查当前 Token 是否仍然有效
    """
    if not authorization:
        return make_response(
            data={
                "valid": False,
                "error": "未提供认证信息"
            }
        )
    
    try:
        # 提取 Token
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise ValueError("无效的认证格式")
        
        token = parts[1]
        
        # 验证 Token
        payload = verify_token(token)

        return make_response(
            data={
                "valid": True,
                "user_info": {
                    "user_id": payload.get("sub"),
                    "username": payload.get("username"),
                    "role": payload.get("role")
                }
            }
        )
        
    except Exception as e:
        return make_response(
            data={
                "valid": False,
                "error": str(e)
            }
        )

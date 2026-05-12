# -*- coding: utf-8 -*-
from common.utils.exceptions import StorageException
"""
file-service 业务层
- 文件上传到对象存储（MinIO）
- 获取预签名下载 URL
- 参考 ragflow api/apps/file_app.py upload 逻辑
"""
import os
import uuid
import urllib.parse
from common.config import settings
from common.storage import get_object_storage
from common.utils import get_logger

logger = get_logger("file_service")

# 支持的文件类型与 MIME 映射（参考 ragflow api/db/__init__.py VALID_FILE_TYPES）
ALLOWED_EXTENSIONS = {
    "pdf", "docx", "doc", "txt", "md", "markdown", "html", "htm", "xlsx", "xls", "csv", "pptx", "ppt", "png", "jpg", "jpeg", "gif", "bmp", "zip", "tar", "gz", "mp4", "avi", "mov", "mp3", "wav", }

MAX_FILE_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "200")) * 1024 * 1024  # 默认 200MB

def _get_file_ext(filename: str) -> str:
    """提取小写后缀"""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

def _build_object_key(tenant_id: str, kb_id: str | None, filename: str) -> str:
    """
    生成对象存储路径
    格式：{tenant_id}/{kb_id}/{uuid}_{filename}  （有知识库时）
           {tenant_id}/tmp/{uuid}_{filename}       （无知识库时）
    参考 ragflow FileService.get_storage_address
    """
    folder = kb_id if kb_id else "tmp"
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    return f"{tenant_id}/{folder}/{unique_name}"

class FileService:
    """文件服务"""

    def __init__(self):
        self.storage = get_object_storage()
        self.bucket = settings.minio.bucket

    async def upload_file(
        self, tenant_id: str, file_data: bytes, filename: str, kb_id: str | None = None, content_type: str | None = None, ) -> tuple[str, str]:
        """
        上传文件到对象存储
        :return: (object_key, presigned_url)
        参考 ragflow file_app.upload
        """
        # 校验文件大小
        if len(file_data) > MAX_FILE_SIZE:
            raise ValueError(f"文件大小超限，最大允许 {MAX_FILE_SIZE // 1024 // 1024}MB")

        # 校验文件类型
        ext = _get_file_ext(filename)
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: .{ext}")

        object_key = _build_object_key(tenant_id, kb_id, filename)

        metadata = {
            "tenant_id": tenant_id, "original_name": urllib.parse.quote(filename), }
        if kb_id:
            metadata["kb_id"] = kb_id
        if content_type:
            metadata["content_type"] = content_type

        await self.storage.put(self.bucket, object_key, file_data, metadata=metadata)
        logger.info(f"Uploaded file: bucket={self.bucket} key={object_key} size={len(file_data)}")

        # 生成预签名下载 URL（7 天有效）
        url = await self.storage.get_url(self.bucket, object_key, expires=7 * 24 * 3600)
        return object_key, url

    async def get_presigned_url(self, object_key: str, expires: int = 3600) -> str:
        """获取预签名下载 URL"""
        url = await self.storage.get_url(self.bucket, object_key, expires=expires)
        return url

    async def get_file_content(self, object_key: str) -> bytes:
        """获取文件内容（供 /ai/knowledge/mdcontent 使用）"""
        data = await self.storage.get(self.bucket, object_key)
        return data

    async def delete_file(self, object_key: str) -> bool:
        """删除文件"""
        await self.storage.delete(self.bucket, object_key)
        logger.info(f"Deleted file: {object_key}")
        return True

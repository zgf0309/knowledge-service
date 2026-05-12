-- ============================================================
-- File Service - 文件存储微服务数据库建表脚本
-- 端口：7103
-- 创建日期：2026-03-23
-- ============================================================

-- 如果表已存在则删除（生产环境请谨慎使用）
-- DROP TABLE IF EXISTS file_record;

-- ============================================================
-- 1. 文件记录表 (file_record)
-- ============================================================
CREATE TABLE IF NOT EXISTS `file_record` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '文件记录 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `user_id` VARCHAR(32) COMMENT '用户 ID',
  
  `file_name` VARCHAR(255) NOT NULL COMMENT '文件名',
  `original_name` VARCHAR(255) COMMENT '原始文件名',
  `file_path` VARCHAR(512) NOT NULL COMMENT '文件路径',
  `file_url` VARCHAR(512) NOT NULL COMMENT '文件 URL',
  `file_size` BIGINT DEFAULT 0 COMMENT '文件大小 (字节)',
  `file_suffix` VARCHAR(16) COMMENT '文件后缀',
  `mime_type` VARCHAR(64) COMMENT 'MIME 类型',
  
  `storage_type` VARCHAR(32) DEFAULT 'minio' COMMENT '存储类型：minio/oss/s3/local',
  `bucket_name` VARCHAR(128) COMMENT '存储桶名称',
  
  `md5_hash` VARCHAR(64) COMMENT 'MD5 哈希值',
  `sha256_hash` VARCHAR(128) COMMENT 'SHA256 哈希值',
  
  `upload_status` VARCHAR(16) DEFAULT 'completed' COMMENT '上传状态：pending/uploading/completed/failed',
  `download_count` INT DEFAULT 0 COMMENT '下载次数',
  
  `metadata` JSON COMMENT '元数据 JSON',
  `tags` JSON COMMENT '标签数组',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_md5_hash` (`md5_hash`),
  INDEX `idx_status` (`status`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文件记录表';

-- ============================================================
-- 示例数据（可选）
-- ============================================================

-- 插入示例文件记录
INSERT INTO `file_record` (`id`, `tenant_id`, `user_id`, `file_name`, `original_name`, `file_path`, `file_url`, `file_size`, `file_suffix`, `mime_type`, `storage_type`, `bucket_name`) 
VALUES ('demo_file_001', 'tenant_001', 'user_001', 'document.pdf', '原始文档.pdf', '/files/tenant_001/document.pdf', 'http://minio:9000/files/tenant_001/document.pdf', 1048576, 'pdf', 'application/pdf', 'minio', 'default')
ON DUPLICATE KEY UPDATE `file_name` = VALUES(`file_name`);

-- ============================================================
-- 权限设置（根据需要调整）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON file_record TO 'your_user'@'%';

-- ============================================================
-- 备注说明
-- ============================================================
-- 1. 所有表使用 InnoDB 引擎，支持事务和外键约束
-- 2. 字符集使用 utf8mb4，支持完整的 UTF-8 编码
-- 3. metadata 和 tags 使用 JSON 类型存储灵活结构
-- 4. md5_hash/sha256_hash 用于文件去重和完整性校验
-- 5. storage_type 支持多种对象存储后端
-- 6. download_count 用于统计文件使用情况
-- 7. 生产环境建议添加软删除触发器或改用逻辑删除方案

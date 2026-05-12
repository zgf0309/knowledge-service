-- ============================================================
-- Model Service - AI 模型管理微服务数据库建表脚本
-- 端口：7104
-- 创建日期：2026-03-23
-- ============================================================

-- 如果表已存在则删除（生产环境请谨慎使用）
-- DROP TABLE IF EXISTS ai_model;
-- DROP TABLE IF EXISTS prompt_template;
-- DROP TABLE IF EXISTS prompt_history;

-- ============================================================
-- 1. AI 模型配置表 (ai_model)
-- ============================================================
CREATE TABLE IF NOT EXISTS `ai_model` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '模型 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `name` VARCHAR(128) NOT NULL COMMENT '模型显示名称',
  `model_type` VARCHAR(32) DEFAULT 'chat' COMMENT '模型类型：chat/embedding/rerank/tts/asr/image',
  `provider` VARCHAR(64) COMMENT '提供商：openai/qwen/ollama/deepseek/...',
  `model_name` VARCHAR(128) NOT NULL COMMENT '模型标识符',
  
  `api_key` VARCHAR(512) COMMENT 'API Key（加密存储）',
  `base_url` VARCHAR(512) COMMENT 'API Base URL',
  `max_tokens` INT DEFAULT 4096 COMMENT '最大 token 数',
  `temperature` FLOAT DEFAULT 0.1 COMMENT '温度参数',
  
  `extra_params` JSON COMMENT '额外参数 JSON',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_model_type` (`model_type`),
  INDEX `idx_provider` (`provider`),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_by` (`created_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 模型配置表';

-- ============================================================
-- 2. 提示词模板表 (prompt_template)
-- ============================================================
CREATE TABLE IF NOT EXISTS `prompt_template` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '模板 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `name` VARCHAR(255) NOT NULL COMMENT '模板名称',
  `template_type` VARCHAR(32) DEFAULT 'custom' COMMENT '模板类型：custom/system/built-in',
  
  `content` LONGTEXT NOT NULL COMMENT '模板内容',
  `variables` JSON COMMENT '变量定义 JSON',
  
  `category` VARCHAR(64) COMMENT '分类：rag/summarize/extract/qa/...',
  `version` VARCHAR(16) DEFAULT '1.0.0' COMMENT '版本号',
  
  `is_public` INT DEFAULT 0 COMMENT '是否公开：0-私有，1-公开',
  `usage_count` INT DEFAULT 0 COMMENT '使用次数',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_template_type` (`template_type`),
  INDEX `idx_category` (`category`),
  INDEX `idx_is_public` (`is_public`),
  INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='提示词模板表';

-- ============================================================
-- 3. 提示词历史表 (prompt_history)
-- ============================================================
CREATE TABLE IF NOT EXISTS `prompt_history` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '历史记录 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `template_id` VARCHAR(32) COMMENT '关联模板 ID',
  
  `content_snapshot` LONGTEXT NOT NULL COMMENT '内容快照',
  `change_reason` TEXT COMMENT '变更原因',
  `version_snapshot` VARCHAR(16) COMMENT '版本快照',
  
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_template_id` (`template_id`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='提示词历史表';

-- ============================================================
-- 示例数据（可选）
-- ============================================================

-- 插入示例 AI 模型配置
INSERT INTO `ai_model` (`id`, `tenant_id`, `name`, `model_type`, `provider`, `model_name`, `max_tokens`, `temperature`) 
VALUES ('model_001', 'tenant_001', 'GPT-4o Mini', 'chat', 'openai', 'gpt-4o-mini', 4096, 0.1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- 插入示例提示词模板
INSERT INTO `prompt_template` (`id`, `tenant_id`, `name`, `template_type`, `content`, `category`, `variables`, `is_public`) 
VALUES ('prompt_001', 'tenant_001', 'RAG 标准问答', 'custom', '你是一个智能助手。请根据以下信息回答问题：\n\n相关信息：{{context}}\n\n问题：{{question}}', 'rag', '["context", "question"]', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- ============================================================
-- 权限设置（根据需要调整）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ai_model TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_template TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON prompt_history TO 'your_user'@'%';

-- ============================================================
-- 备注说明
-- ============================================================
-- 1. 所有表使用 InnoDB 引擎，支持事务和外键约束
-- 2. 字符集使用 utf8mb4，支持完整的 UTF-8 编码
-- 3. api_key 应该加密存储（建议使用 3DES 或 AES）
-- 4. extra_params 和 variables 使用 JSON 类型存储灵活结构
-- 5. prompt_history 用于记录模板变更历史，支持版本回溯
-- 6. usage_count 用于统计模板使用情况
-- 7. 生产环境建议添加软删除触发器或改用逻辑删除方案

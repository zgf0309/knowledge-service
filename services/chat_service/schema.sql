-- ============================================================
-- Chat Service - 对话服务微服务数据库建表脚本
-- 端口：7105
-- 创建日期：2026-03-23
-- ============================================================

-- 如果表已存在则删除（生产环境请谨慎使用）
-- DROP TABLE IF EXISTS app;
-- DROP TABLE IF EXISTS session;
-- DROP TABLE IF EXISTS message;

-- ============================================================
-- 1. 应用配置表 (app)
-- ============================================================
CREATE TABLE IF NOT EXISTS `app` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '应用 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `name` VARCHAR(255) NOT NULL COMMENT '应用名称',
  `description` TEXT COMMENT '应用描述',
  `icon` VARCHAR(512) COMMENT '图标 URL',
  `app_type` VARCHAR(32) DEFAULT 'chat' COMMENT '应用类型：chat/flow/agent',
  
  -- 模型配置
  `model_id` VARCHAR(32) COMMENT '关联 AI 模型 ID',
  `temperature` FLOAT DEFAULT 0.1 COMMENT '温度参数',
  `max_tokens` INT DEFAULT 4096 COMMENT '最大 token 数',
  
  -- 提示词
  `system_prompt` LONGTEXT COMMENT '系统提示词',
  `prompt_template` LONGTEXT COMMENT '提示词模板',
  
  -- 关联知识库（JSON 数组，存知识库 ID 列表）
  `kb_ids` JSON COMMENT '关联知识库 ID 列表',
  
  -- RAG 配置
  `top_k` INT DEFAULT 5 COMMENT '检索 TopK',
  `similarity_threshold` FLOAT DEFAULT 0.2 COMMENT '相似度阈值',
  `rerank_enabled` INT DEFAULT 0 COMMENT '是否启用重排',
  `rerank_model_id` VARCHAR(32) COMMENT '重排模型 ID',
  
  -- 记忆与历史
  `history_window` INT DEFAULT 10 COMMENT '历史对话轮数',
  `memory_enabled` INT DEFAULT 0 COMMENT '是否启用记忆',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_app_type` (`app_type`),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_by` (`created_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='应用配置表';

-- ============================================================
-- 2. 会话记录表 (session)
-- ============================================================
CREATE TABLE IF NOT EXISTS `session` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '会话 ID',
  `app_id` VARCHAR(32) NOT NULL COMMENT '应用 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `user_id` VARCHAR(32) COMMENT '用户 ID',
  
  -- 对话内容
  `question` LONGTEXT COMMENT '用户问题',
  `answer` LONGTEXT COMMENT 'AI 回答',
  `messages` JSON COMMENT '完整消息列表',
  
  -- 检索结果
  `reference_chunks` JSON COMMENT '引用切片列表',
  
  -- 元数据
  `total_tokens` INT DEFAULT 0 COMMENT '总 token 数',
  `duration_ms` INT DEFAULT 0 COMMENT '耗时（毫秒）',
  
  -- 反馈信息
  `feedback_score` INT COMMENT '反馈评分：1-5',
  `feedback_comment` TEXT COMMENT '反馈评论',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_app_id` (`app_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_status` (`status`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话记录表';

-- ============================================================
-- 3. 消息记录表 (message)
-- ============================================================
CREATE TABLE IF NOT EXISTS `message` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '消息 ID',
  `session_id` VARCHAR(32) NOT NULL COMMENT '会话 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  
  `role` VARCHAR(16) DEFAULT 'user' COMMENT '角色：user/assistant/system',
  `content` LONGTEXT NOT NULL COMMENT '消息内容',
  
  `tokens` INT DEFAULT 0 COMMENT 'token 数量',
  `metadata` JSON COMMENT '元数据',
  
  `position` INT DEFAULT 0 COMMENT '在会话中的位置',
  `parent_message_id` VARCHAR(32) COMMENT '父消息 ID（分支对话）',
  
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  
  INDEX `idx_session_id` (`session_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_role` (`role`),
  INDEX `idx_parent_message_id` (`parent_message_id`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息记录表';

-- ============================================================
-- 4. QA 库表 (qa_library)
-- ============================================================
CREATE TABLE IF NOT EXISTS `qa_library` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT 'QA 库 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `qa_name` VARCHAR(255) NOT NULL COMMENT 'QA 库名称',
  `qa_desc` TEXT COMMENT 'QA 库描述',
  `aigc_model_id` VARCHAR(64) COMMENT 'AI 模型 ID',
  `icon_url` VARCHAR(512) COMMENT '图标 URL',
  `status` TINYINT DEFAULT 1 COMMENT '状态：0-禁用，1-启用',
  
  -- 统计信息
  `item_count` INT DEFAULT 0 COMMENT 'QA 条目数量',
  `use_count` BIGINT DEFAULT 0 COMMENT '使用次数',
  
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_by` (`created_by`),
  INDEX `idx_qa_name` (`qa_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='QA 库表';

-- ============================================================
-- 5. QA 条目表 (qa_item)
-- ============================================================
CREATE TABLE IF NOT EXISTS `qa_item` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT 'QA 条目 ID',
  `qa_lib_id` VARCHAR(32) NOT NULL COMMENT 'QA 库 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  
  `question` TEXT NOT NULL COMMENT '问题',
  `answer` TEXT NOT NULL COMMENT '答案',
  `qa_modal` TINYINT DEFAULT 0 COMMENT 'QA 模式：0-普通，1-高级',
  
  -- 扩展字段
  `tags` JSON COMMENT '标签列表',
  `similarity_questions` JSON COMMENT '相似问题列表',
  
  -- 统计信息
  `use_count` BIGINT DEFAULT 0 COMMENT '使用次数',
  `feedback_score` FLOAT DEFAULT 0 COMMENT '平均评分',
  
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  -- 全文索引（用于搜索）
  FULLTEXT KEY `idx_question_answer` (`question`, `answer`(255)) WITH PARSER ngram,
  INDEX `idx_qa_lib_id` (`qa_lib_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='QA 条目表';

-- ============================================================
-- 6. 反馈表 (feedback)
-- ============================================================
CREATE TABLE IF NOT EXISTS `feedback` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '反馈 ID',
  `session_id` VARCHAR(32) COMMENT '会话 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `user_id` VARCHAR(32) COMMENT '用户 ID',
  
  `score` TINYINT COMMENT '评分：1-5',
  `comment` TEXT COMMENT '评论内容',
  `feedback_type` VARCHAR(32) COMMENT '反馈类型：like/dislike',
  
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  
  INDEX `idx_session_id` (`session_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_create_date` (`create_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='反馈表';

-- ============================================================
-- 示例数据（可选）
-- ============================================================

-- 插入示例应用
INSERT INTO `app` (`id`, `tenant_id`, `name`, `description`, `app_type`, `model_id`, `top_k`, `history_window`) 
VALUES ('demo_app_001', 'tenant_001', '智能客服助手', '用于回答客户问题的 AI 助手', 'chat', 'model_001', 5, 10)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- 插入示例会话
INSERT INTO `session` (`id`, `app_id`, `tenant_id`, `user_id`, `question`, `answer`, `total_tokens`, `duration_ms`) 
VALUES ('demo_session_001', 'demo_app_001', 'tenant_001', 'user_001', '你好', '你好！有什么我可以帮助你的吗？', 50, 200)
ON DUPLICATE KEY UPDATE `question` = VALUES(`question`);

-- 插入示例消息
INSERT INTO `message` (`id`, `session_id`, `tenant_id`, `role`, `content`, `tokens`, `position`) 
VALUES ('demo_msg_001', 'demo_session_001', 'tenant_001', 'user', '你好', 10, 0)
ON DUPLICATE KEY UPDATE `content` = VALUES(`content`);

-- 插入示例 QA 库
INSERT INTO `qa_library` (`id`, `tenant_id`, `qa_name`, `qa_desc`, `aigc_model_id`, `status`, `item_count`) 
VALUES ('demo_qa_lib_001', 'tenant_001', '客服常见问题库', '客服团队常用问题解答', 'gpt-4', 1, 156)
ON DUPLICATE KEY UPDATE `qa_name` = VALUES(`qa_name`);

-- 插入示例 QA 条目
INSERT INTO `qa_item` (`id`, `qa_lib_id`, `tenant_id`, `question`, `answer`, `qa_modal`) 
VALUES ('demo_qa_item_001', 'demo_qa_lib_001', 'tenant_001', '如何重置密码？', '请访问个人中心，点击"忘记密码"链接，按照提示操作即可。', 0)
ON DUPLICATE KEY UPDATE `question` = VALUES(`question`);

INSERT INTO `qa_item` (`id`, `qa_lib_id`, `tenant_id`, `question`, `answer`, `qa_modal`) 
VALUES ('demo_qa_item_002', 'demo_qa_lib_001', 'tenant_001', '如何联系人工客服？', '请拨打客服热线：400-xxx-xxxx，按 0 转人工服务。', 0)
ON DUPLICATE KEY UPDATE `question` = VALUES(`question`);

-- ============================================================
-- 权限设置（根据需要调整）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON app TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON session TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON message TO 'your_user'@'%';

-- ============================================================
-- 备注说明
-- ============================================================
-- 1. 所有表使用 InnoDB 引擎，支持事务和外键约束
-- 2. 字符集使用 utf8mb4，支持完整的 UTF-8 编码
-- 3. messages 字段存储完整的对话历史（JSON 数组）
-- 4. reference_chunks 存储检索到的知识切片
-- 5. parent_message_id 支持分支对话场景
-- 6. feedback_score 和 feedback_comment 用于质量评估
-- 7. 生产环境建议添加软删除触发器或改用逻辑删除方案

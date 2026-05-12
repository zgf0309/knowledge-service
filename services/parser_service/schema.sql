-- ============================================================
-- Parser Service - 文档解析微服务数据库建表脚本
-- 端口：7106
-- 创建日期：2026-03-23
-- ============================================================

-- 如果表已存在则删除（生产环境请谨慎使用）
-- DROP TABLE IF EXISTS parse_task;
-- DROP TABLE IF EXISTS parse_result;

-- ============================================================
-- 1. 解析任务表 (parse_task)
-- ============================================================
CREATE TABLE IF NOT EXISTS `parse_task` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '任务 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `doc_id` VARCHAR(32) NOT NULL COMMENT '文档 ID',
  `kb_id` VARCHAR(32) COMMENT '知识库 ID',
  
  `task_type` VARCHAR(32) DEFAULT 'parse' COMMENT '任务类型：parse/embedding/graphrag/raptor',
  `parser_id` VARCHAR(32) DEFAULT 'naive' COMMENT '解析器类型',
  `parser_config` JSON COMMENT '解析配置 JSON',
  
  -- 分页处理
  `from_page` INT DEFAULT 0 COMMENT '起始页',
  `to_page` INT DEFAULT 100000000 COMMENT '结束页',
  
  -- 执行状态
  `priority` INT DEFAULT 0 COMMENT '优先级',
  `progress` FLOAT DEFAULT 0 COMMENT '进度百分比',
  `progress_msg` TEXT COMMENT '进度消息',
  `status` VARCHAR(16) DEFAULT 'pending' COMMENT '状态：pending/running/completed/failed',
  `retry_count` INT DEFAULT 0 COMMENT '重试次数',
  
  -- 结果信息
  `chunk_ids` LONGTEXT COMMENT '切片 ID 列表（JSON 数组）',
  `digest` TEXT COMMENT '摘要',
  `result` JSON COMMENT '执行结果 JSON',
  `error_msg` TEXT COMMENT '错误信息',
  
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_doc_id` (`doc_id`),
  INDEX `idx_kb_id` (`kb_id`),
  INDEX `idx_task_type` (`task_type`),
  INDEX `idx_status` (`status`),
  INDEX `idx_priority` (`priority`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='解析任务表';

-- ============================================================
-- 2. 解析结果表 (parse_result)
-- ============================================================
CREATE TABLE IF NOT EXISTS `parse_result` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '结果 ID',
  `task_id` VARCHAR(32) NOT NULL COMMENT '关联任务 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `doc_id` VARCHAR(32) NOT NULL COMMENT '文档 ID',
  `kb_id` VARCHAR(32) COMMENT '知识库 ID',
  
  -- 切片内容
  `chunk_index` INT DEFAULT 0 COMMENT '切片索引',
  `content` LONGTEXT COMMENT '切片内容',
  `content_with_weight` FLOAT DEFAULT 1.0 COMMENT '内容权重',
  
  -- 向量数据
  `vector` LONGTEXT COMMENT '向量数据（JSON 数组）',
  `embedding_model_id` VARCHAR(32) COMMENT '嵌入模型 ID',
  
  -- 元数据
  `token_num` INT DEFAULT 0 COMMENT 'Token 数量',
  `metadata` JSON COMMENT '元数据 JSON',
  
  -- 位置信息
  `page_num` INT COMMENT '页码',
  `position` VARCHAR(64) COMMENT '位置信息',
  
  -- 关键词
  `important_keywords` JSON COMMENT '重要关键词列表',
  `keyword_explanations` JSON COMMENT '关键词解释字典 {keyword: explanation}',
  
  -- 状态
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_task_id` (`task_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_doc_id` (`doc_id`),
  INDEX `idx_kb_id` (`kb_id`),
  INDEX `idx_chunk_index` (`chunk_index`),
  INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='解析结果表';

-- ============================================================
-- 示例数据（可选）
-- ============================================================

-- 插入示例解析任务
INSERT INTO `parse_task` (`id`, `tenant_id`, `doc_id`, `kb_id`, `task_type`, `parser_id`, `status`, `progress`) 
VALUES ('demo_parse_task_001', 'tenant_001', 'doc_001', 'kb_001', 'parse', 'naive', 'completed', 100.0)
ON DUPLICATE KEY UPDATE `task_type` = VALUES(`task_type`);

-- 插入示例解析结果
INSERT INTO `parse_result` (`id`, `task_id`, `tenant_id`, `doc_id`, `kb_id`, `chunk_index`, `content`, `token_num`, `status`) 
VALUES ('demo_chunk_001', 'demo_parse_task_001', 'tenant_001', 'doc_001', 'kb_001', 0, '这是文档的第一个切片内容...', 512, '1')
ON DUPLICATE KEY UPDATE `content` = VALUES(`content`);

-- ============================================================
-- 权限设置（根据需要调整）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON parse_task TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON parse_result TO 'your_user'@'%';

-- ============================================================
-- 备注说明
-- ============================================================
-- 1. 所有表使用 InnoDB 引擎，支持事务和外键约束
-- 2. 字符集使用 utf8mb4，支持完整的 UTF-8 编码
-- 3. parser_config 使用 JSON 存储不同解析器的配置
-- 4. chunk_ids 使用 LONGTEXT 存储大量切片 ID（JSON 数组）
-- 5. vector 使用 LONGTEXT 存储高维向量数据（JSON 数组）
-- 6. metadata 和 important_keywords 使用 JSON 类型
-- 7. 支持多种任务类型：parse/embedding/graphrag/raptor
-- 8. 生产环境建议添加软删除触发器或改用逻辑删除方案

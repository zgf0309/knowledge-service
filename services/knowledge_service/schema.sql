-- ============================================================
-- Knowledge Service - 知识库微服务数据库建表脚本
-- 端口：7101
-- 创建日期：2026-03-23
-- ============================================================

-- 如果表已存在则删除（生产环境请谨慎使用）
-- DROP TABLE IF EXISTS knowledge_base;

-- ============================================================
-- 1. 知识库表 (knowledge_base)
-- ============================================================
CREATE TABLE IF NOT EXISTS `knowledge_base` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '知识库 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID/组织 ID',
  `name` VARCHAR(255) NOT NULL COMMENT '知识库名称',
  `description` TEXT COMMENT '知识库描述',
  `language` VARCHAR(32) DEFAULT 'Chinese' COMMENT '语言',
  `permission` VARCHAR(16) DEFAULT 'me' COMMENT '权限：me, team, public',
  
  `embedding_model_id` VARCHAR(128) COMMENT '嵌入模型 ID',
  `embedding_model_path` VARCHAR(255) COMMENT '嵌入模型路径',
  `embedding_dims` INT DEFAULT 1024 COMMENT '向量维度',
  
  `parser_id` VARCHAR(32) DEFAULT 'naive' COMMENT '解析器类型',
  `parser_config` JSON COMMENT '解析配置 JSON',
  
  `doc_num` INT DEFAULT 0 COMMENT '文档数量',
  `token_num` BIGINT DEFAULT 0 COMMENT 'Token 数量',
  `chunk_num` INT DEFAULT 0 COMMENT '切片数量',
  
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-禁用，1-激活，2-删除',
  
  `graph_enabled` INT DEFAULT 0 COMMENT '是否启用知识图谱：0-否，1-是',
  `graph_task_id` VARCHAR(32) COMMENT '图谱任务 ID',
  
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_by` (`created_by`),
  INDEX `idx_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库表';

-- ============================================================
-- 示例数据（可选）
-- ============================================================

-- 插入示例知识库
INSERT INTO `knowledge_base` (`id`, `tenant_id`, `name`, `description`, `language`, `permission`, `parser_id`, `status`) 
VALUES ('demo_kb_001', 'tenant_001', '示例知识库', '这是一个演示用的知识库', 'Chinese', 'team', 'naive', '1')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- 插入内置清洗规则
INSERT INTO `document_clean_rule` (`id`, `tenant_id`, `rule_name`, `rule_content`, `rule_desc`, `rule_type`, `doc_type`, `is_builtin`) 
VALUES 
('builtin_clean_001', 'system', '移除 ASCII 不可见字符', '移除 ASCII 中 0-32 和 127-160 范围的不可见字符', '移除控制字符和空格', 0, 0, 1),
('builtin_clean_002', 'system', '去除多余空格', '将连续的空格、制表符替换为单个空格', '清理空白字符', 0, 0, 1),
('builtin_clean_003', 'system', '去除乱码和无意义 unicode', '移除无意义的 Unicode 字符和乱码', '清理乱码', 0, 0, 1),
('builtin_clean_004', 'system', '繁体转简体', '将繁体字转换为简体字', '简繁转换', 0, 0, 1),
('builtin_clean_005', 'system', '清除 QA 对无意义符号', '清除如"Q:", "A:", "、、、"等无实际意义的符号', 'QA 清洗', 0, 3, 1),
('builtin_clean_006', 'system', '去除 HTML 标签', '移除所有 HTML 标签，如<html>, <div>, <p>等', 'HTML 清理', 0, 1, 1),
('builtin_clean_007', 'system', '去除 Markdown 标记', '移除 Markdown 标记，如#, ##, ###, **, _等', 'Markdown 清理', 0, 1, 1),
('builtin_clean_008', 'system', 'Unicode 规范化 (NFKC)', '使用 NFKC 规范化 Unicode，全角转半角，统一字符表示', 'Unicode 规范化', 0, 0, 1),
('builtin_clean_009', 'system', '去除 Emoji 表情', '移除所有 Emoji 表情符号（包括笑脸、手势、交通标志等）', 'Emoji 清理', 0, 0, 1);

-- ============================================================
-- 7. 文档清洗规则表 (document_clean_rule)
-- ============================================================
CREATE TABLE IF NOT EXISTS `document_clean_rule` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '规则 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `rule_name` VARCHAR(255) NOT NULL COMMENT '规则名称',
  `rule_content` TEXT NOT NULL COMMENT '规则内容（提示词/脚本）',
  `rule_desc` TEXT COMMENT '规则描述',
  `rule_type` TINYINT NOT NULL DEFAULT 0 COMMENT '规则类型：0-脚本处理，1-模型处理',
  `doc_type` TINYINT NOT NULL DEFAULT 0 COMMENT '适用文档类型：0-通用，1-文本，2-Excel, 3-QA',
  `is_builtin` TINYINT DEFAULT 0 COMMENT '是否内置：0-否，1-是',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_rule_type` (`rule_type`),
  INDEX `idx_doc_type` (`doc_type`),
  INDEX `idx_is_builtin` (`is_builtin`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档清洗规则表';

-- ============================================================
-- 8. 文档清洗关联表 (document_rule_relation)
-- ============================================================
CREATE TABLE IF NOT EXISTS `document_rule_relation` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '关联 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `document_id` VARCHAR(32) NOT NULL COMMENT '文档 ID',
  `rule_id` VARCHAR(32) NOT NULL COMMENT '规则 ID',
  `rule_type` TINYINT NOT NULL DEFAULT 0 COMMENT '规则类型：0-脚本，1-模型',
  `priority` INT DEFAULT 0 COMMENT '执行优先级',
  `enabled` TINYINT DEFAULT 1 COMMENT '是否启用：0-否，1-是',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  
  UNIQUE KEY `uk_document_rule` (`document_id`, `rule_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_document_id` (`document_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档清洗关联表';

-- ============================================================
-- 9. 知识库清洗预配置表 (knowledge_rule_preset)
-- ============================================================
CREATE TABLE IF NOT EXISTS `knowledge_rule_preset` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '预配置 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `knowledge_id` VARCHAR(32) NOT NULL COMMENT '知识库 ID',
  `rule_id` VARCHAR(32) NOT NULL COMMENT '规则 ID',
  `rule_type` TINYINT NOT NULL DEFAULT 0 COMMENT '规则类型：0-脚本，1-模型',
  `enabled` TINYINT DEFAULT 1 COMMENT '是否启用：0-否，1-是',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  
  UNIQUE KEY `uk_knowledge_rule` (`knowledge_id`, `rule_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_knowledge_id` (`knowledge_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库清洗预配置表';

-- ============================================================
-- 10. 文档清洗任务表 (document_clean_task)
-- ============================================================
CREATE TABLE IF NOT EXISTS `document_clean_task` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '任务 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `knowledge_id` VARCHAR(32) NOT NULL COMMENT '知识库 ID',
  `document_id` VARCHAR(32) NOT NULL COMMENT '文档 ID',
  `task_type` VARCHAR(32) DEFAULT 'clean' COMMENT '任务类型：clean-清洗，filter-过滤',
  
  -- 任务状态
  `state` VARCHAR(16) DEFAULT 'pending' COMMENT '状态：pending/running/completed/failed',
  `progress` FLOAT DEFAULT 0 COMMENT '进度：0-100',
  `progress_msg` TEXT COMMENT '进度消息',
  
  -- 结果
  `original_url` VARCHAR(1024) COMMENT '原始文档 URL',
  `cleaned_url` VARCHAR(1024) COMMENT '清洗后文档 URL',
  `cleaned_content` LONGTEXT COMMENT '清洗后内容（文本）',
  `statistics` JSON COMMENT '统计信息',
  
  -- 错误信息
  `error_msg` TEXT COMMENT '错误信息',
  `retry_count` INT DEFAULT 0 COMMENT '重试次数',
  
  `aigc_model_id` VARCHAR(64) COMMENT '使用的 AI 模型 ID',
  `rules_applied` JSON COMMENT '应用的规则列表',
  
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `start_time` BIGINT COMMENT '开始时间戳（毫秒）',
  `end_time` BIGINT COMMENT '结束时间戳（毫秒）',
  
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_knowledge_id` (`knowledge_id`),
  INDEX `idx_document_id` (`document_id`),
  INDEX `idx_state` (`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档清洗任务表';

-- ============================================================
-- 11. 知识库群组表 (knowledge_group)
-- ============================================================
CREATE TABLE IF NOT EXISTS `knowledge_group` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '群组 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `name` VARCHAR(255) NOT NULL COMMENT '群组名称',
  `description` TEXT COMMENT '群组描述',
  `parent_id` VARCHAR(32) DEFAULT NULL COMMENT '父群组 ID，NULL 表示根群组',
  `path` VARCHAR(1024) DEFAULT '' COMMENT '祖先路径：/root_id/parent_id/self_id/，便于子树查询',
  `depth` INT DEFAULT 0 COMMENT '层级深度，根节点为 0',
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',

  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_parent_id` (`parent_id`),
  INDEX `idx_path` (`path`(255)),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_by` (`created_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库群组表（邻接表，支持无限层级）';

-- ============================================================
-- 12. 群组成员角色表 (knowledge_group_member)
-- ============================================================
CREATE TABLE IF NOT EXISTS `knowledge_group_member` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '记录 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `group_id` VARCHAR(32) NOT NULL COMMENT '群组 ID',
  `user_id` VARCHAR(32) NOT NULL COMMENT '用户 ID',
  `role` VARCHAR(16) DEFAULT 'member' COMMENT '角色：owner/admin/member/viewer',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',

  UNIQUE KEY `uk_group_user` (`group_id`, `user_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_group_id` (`group_id`),
  INDEX `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库群组成员角色表';

-- ============================================================
-- knowledge_base 表扩展：添加群组归属字段
-- ============================================================
-- 如果表已存在（升级场景），执行以下 ALTER；新建环境 CREATE 语句中已包含此字段
ALTER TABLE `knowledge_base`
  ADD COLUMN IF NOT EXISTS `group_id` VARCHAR(32) DEFAULT NULL COMMENT '所属群组 ID，NULL 表示未归属任何群组';

ALTER TABLE `knowledge_base`
  ADD INDEX IF NOT EXISTS `idx_group_id` (`group_id`);

-- ============================================================
-- 13. 用户权限组表 (user_permission_group)
-- 独立于知识库群组：将一批用户打包为一个权限组，
-- 再整体授权给某个知识库或知识库群组，实现批量授权
-- ============================================================
CREATE TABLE IF NOT EXISTS `user_permission_group` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '权限组 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `name` VARCHAR(255) NOT NULL COMMENT '权限组名称',
  `description` TEXT COMMENT '权限组描述',
  `status` VARCHAR(1) DEFAULT '1' COMMENT '状态：0-删除，1-激活',
  `created_by` VARCHAR(32) COMMENT '创建者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',

  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_created_by` (`created_by`),
  INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户权限组表（与知识库群组正交，仅用于批量授权）';

-- ============================================================
-- 14. 用户权限组成员表 (user_permission_group_member)
-- 记录哪些用户属于哪个权限组
-- ============================================================
CREATE TABLE IF NOT EXISTS `user_permission_group_member` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '记录 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',
  `perm_group_id` VARCHAR(32) NOT NULL COMMENT '权限组 ID',
  `user_id` VARCHAR(32) NOT NULL COMMENT '用户 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',

  UNIQUE KEY `uk_perm_group_user` (`perm_group_id`, `user_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_perm_group_id` (`perm_group_id`),
  INDEX `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户权限组成员表';

-- ============================================================
-- 15. 知识库权限授权表 (kb_permission_grant)
-- 将「用户」或「用户权限组」授予某个「知识库」或「知识库群组」的访问权限
-- subject_type: user | perm_group
-- target_type:  kb   | kb_group
-- role:         owner | admin | member | viewer
-- ============================================================
CREATE TABLE IF NOT EXISTS `kb_permission_grant` (
  `id` VARCHAR(32) PRIMARY KEY COMMENT '授权记录 ID',
  `tenant_id` VARCHAR(32) NOT NULL COMMENT '租户 ID',

  -- 授权主体
  `subject_type` VARCHAR(16) NOT NULL COMMENT '主体类型：user / perm_group',
  `subject_id` VARCHAR(32) NOT NULL COMMENT '主体 ID（user_id 或 perm_group_id）',

  -- 授权目标
  `target_type` VARCHAR(16) NOT NULL COMMENT '目标类型：kb / kb_group',
  `target_id` VARCHAR(32) NOT NULL COMMENT '目标 ID（knowledge_base.id 或 knowledge_group.id）',

  -- 权限
  `role` VARCHAR(16) NOT NULL DEFAULT 'viewer' COMMENT '权限角色：owner/admin/member/viewer',

  `created_by` VARCHAR(32) COMMENT '授权操作者 ID',
  `create_time` BIGINT COMMENT '创建时间戳（毫秒）',
  `create_date` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建日期',
  `update_time` BIGINT COMMENT '更新时间戳（毫秒）',
  `update_date` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新日期',

  UNIQUE KEY `uk_grant` (`subject_type`, `subject_id`, `target_type`, `target_id`),
  INDEX `idx_tenant_id` (`tenant_id`),
  INDEX `idx_subject` (`subject_type`, `subject_id`),
  INDEX `idx_target` (`target_type`, `target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库权限授权表（支持按用户/权限组授权给知识库/知识库群组）';

-- ============================================================
-- 权限设置（根据需要调整）
-- ============================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_base TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_group TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_group_member TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON user_permission_group TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON user_permission_group_member TO 'your_user'@'%';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON kb_permission_grant TO 'your_user'@'%';

-- ============================================================
-- 备注说明
-- ============================================================
-- 1. 所有表使用 InnoDB 引擎，支持事务和外键约束
-- 2. 字符集使用 utf8mb4，支持完整的 UTF-8 编码（包括 emoji）
-- 3. create_time/update_time 使用 BIGINT 存储毫秒级时间戳
-- 4. create_date/update_date 使用 DATETIME 便于 SQL 查询
-- 5. parser_config 使用 JSON 类型存储灵活的解析配置
-- 6. permission 字段映射到前端 scope：team→0, me→1
-- 7. graph_enabled 标记是否启用 GraphRAG 功能
-- 8. 生产环境建议添加软删除触发器或改用逻辑删除方案
-- 9. knowledge_group.path 格式：/root_id/child_id/，便于子树查询（LIKE '/group_id/%'）
-- 10. knowledge_group_member.role 层级：owner > admin > member > viewer

-- ============================================================
-- document 表扩展：精细化文档导入字段
-- ============================================================
ALTER TABLE `document`
  ADD COLUMN IF NOT EXISTS `doc_category` VARCHAR(32) DEFAULT 'text' COMMENT '文档分类：text/table/web/image/audio',
  ADD COLUMN IF NOT EXISTS `template_type` VARCHAR(32) DEFAULT NULL COMMENT '模板类型：legal/contract/resume/ppt/paper/qa',
  ADD COLUMN IF NOT EXISTS `tags` JSON DEFAULT NULL COMMENT '自定义标签列表',
  ADD COLUMN IF NOT EXISTS `source_url` VARCHAR(2048) DEFAULT NULL COMMENT '网页/远程来源 URL';

ALTER TABLE `document`
  ADD INDEX IF NOT EXISTS `idx_doc_category` (`doc_category`),
  ADD INDEX IF NOT EXISTS `idx_template_type` (`template_type`);

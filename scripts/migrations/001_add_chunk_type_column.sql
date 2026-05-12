-- -*- coding: utf-8 -*-
"""
数据库迁移脚本：为 chunk 表添加 chunk_type 字段
用于区分原文切片和自定义切片

执行时间: 2026-04-28
"""
-- MySQL 迁移：为 chunk 表添加 chunk_type 字段
ALTER TABLE `chunk`
ADD COLUMN `chunk_type` VARCHAR(16) NOT NULL DEFAULT 'original' COMMENT '切片类型: original=原文切片, custom=自定义切片' AFTER `status`;

-- 创建索引加速按类型查询
CREATE INDEX IF NOT EXISTS `idx_chunk_type` ON `chunk` (`chunk_type`);

-- 组合索引加速按文档+类型查询
CREATE INDEX IF NOT EXISTS `idx_doc_type` ON `chunk` (`doc_id`, `chunk_type`);

-- 注意：如果上面的组合索引创建失败（MySQL 8.0 之前不支持 IF NOT EXISTS），请手动执行：
-- CREATE INDEX `idx_doc_type` ON `chunk` (`doc_id`, `chunk_type`);

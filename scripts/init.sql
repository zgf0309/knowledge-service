-- ============================================================
-- Galaxy RAG 数据库初始化脚本
-- ============================================================

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS `galaxy_rag` 
DEFAULT CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- 创建用户并授权（生产环境请使用强密码）
CREATE USER IF NOT EXISTS 'galaxy_rag'@'%' IDENTIFIED BY 'galaxy_rag123';
GRANT ALL PRIVILEGES ON galaxy_rag.* TO 'galaxy_rag'@'%';
FLUSH PRIVILEGES;

-- 切换到 galaxy_rag 数据库
USE `galaxy_rag`;

-- 显示当前数据库信息
SELECT DATABASE() AS current_database;
SELECT USER() AS current_user;

-- 提示：各微服务的 schema.sql 会自动创建表结构
-- 执行顺序：先执行此脚本，再执行各服务的 schema.sql
-- 
-- 示例：
-- mysql -u root -p < init.sql
-- for service in services/*/schema.sql; do mysql -u root -p galaxy_rag < "$service"; done

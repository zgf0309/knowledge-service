# knowledge-web 本地精简版

本目录已按 `knowledge-web` 当前前端调用精简，只保留知识库前端需要的最小后端。

## 运行方式

- **存储环境**：MySQL 使用本机已有数据库；Redis、MinIO、Elasticsearch 使用本机 Docker。
- **后端服务**：直接在本机 Python 进程运行，方便调试代码。
- **前端访问**：`knowledge-web` 通过 `/knowledge-api` 代理到 `http://localhost:8010` 或你配置的网关地址。

## 保留内容

- `services/gateway`：API 网关、SSO 登录路由、请求转发
- `services/knowledge_service`：知识库、知识树、文档导入/运行/停止
- `services/file_service`：文件上传、Markdown 原文读取
- `services/model_service`：Embedding 模型列表
- `services/chat_service`：前端对话创建/历史查询
- `services/parser_service`：文档切片 chunk 接口
- `common`：公共配置、数据库模型、存储工具
- `scripts`：本地启动/停止脚本、数据库初始化和迁移 SQL
- `docs/FRONTEND_BACKEND_GUIDE.md`：前后端接口对照

## 1. 准备本地配置

已经提供本地配置文件：

```text
.env
.env.local.example
```

默认连接本机端口：

```text
MySQL          localhost:3306
Redis          localhost:6379
MinIO          localhost:9000，控制台 localhost:9001
Elasticsearch  localhost:9200
Gateway        localhost:8010
```

## 2. 一键启动本地开发环境

```bash
cd knowledge-service
./scripts/start-local.sh
```

这个命令会自动启动：

- 启动前清理旧本地进程：历史 pid、后端服务模块进程、前端 dev 进程
- 启动前删除旧 Docker Compose 项目：`jusure_microservices2` 的容器和网络
- Docker 存储环境：Redis、MinIO、Elasticsearch（默认不启动 Docker MySQL）
- Python 后端服务：gateway、knowledge、file、model、chat、parser、parse consumer
- 同级目录里的 `knowledge-web` 前端开发服务（如果依赖已安装）

首次启动会自动创建 Docker volume，不再把存储文件写进项目目录。启动脚本只删除容器和网络，不主动删除 Docker volume，避免误删本地数据。

如果确实需要临时使用 Docker MySQL，可以显式开启：

```bash
START_DOCKER_MYSQL=true MYSQL_PORT=3307 ./scripts/start-local.sh
```

如果只想启动后端和存储环境，不启动前端：

```bash
START_WEB=false ./scripts/start-local.sh
```

如果 Docker 存储环境已经在运行，只想重启后端/前端：

```bash
START_INFRA=false ./scripts/start-local.sh
```

## 3. 首次运行前安装依赖

首次运行前需要准备 Python 虚拟环境：

```bash
cd knowledge-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r common/requirements.txt
pip install -r services/gateway/requirements.txt
pip install -r services/parser_service/requirements.txt
pip install -r services/knowledge_service/requirements.txt
```

如果某些大依赖安装慢，可以先只启动网关、知识库、文件、模型、聊天服务，解析/向量相关功能后续再补。

前端首次运行前需要在同级 `knowledge-web` 目录安装依赖：

```bash
cd "../knowledge-web"
yarn install
```

## 4. 常用命令

查看日志：

```bash
tail -f logs/gateway.log
```

停止服务：

```bash
./scripts/stop-local.sh
```

健康检查：

```bash
./scripts/check-local.sh
```

或单独检查网关：

```bash
curl http://localhost:8010/health
```

## 5. 前端代理建议

`knowledge-web/config/proxy.ts` 里本地开发建议指向：

```ts
target: "http://localhost:8010";
```

当前前端请求路径形如：

```text
/knowledge-api/api/v1/ai/knowledge/group
```

会被代理到：

```text
http://localhost:8010/api/v1/ai/knowledge/group
```

## 6. 推荐阅读顺序

1. `docs/FRONTEND_BACKEND_GUIDE.md`
2. `services/gateway/gateway_config.yaml`
3. `services/knowledge_service/api.py`
4. `services/knowledge_service/core_services.py`
5. `common/models/models.py`

## 已删除内容

未被当前 `knowledge-web/src/services` 直接使用的微服务、历史报告、测试脚本、Docker 运行数据、日志、缓存、RAGFlow 适配大包等都已移除。后续如需要图谱、媒体处理、流程编排、监控等能力，可重新安装或从原始工程恢复。

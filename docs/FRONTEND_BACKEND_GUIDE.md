# knowledge-web 与后端接口对照（新手版）

本文只记录当前 `knowledge-web/src/services` 中实际调用的后端接口，方便新同学从前端页面一路找到后端代码。

## 入口关系

- 前端统一前缀：`/knowledge-api`
- 本地开发代理目标：`http://192.168.188.212:8000`（API Gateway）
- 网关入口代码：`services/gateway/main.py`
- 网关转发规则：`services/gateway/gateway_config.yaml`

示例：

```text
knowledge-web 调用 /knowledge-api/api/v1/ai/knowledge/group
  -> 代理到 API Gateway /api/v1/ai/knowledge/group
  -> 网关转发到 knowledge-service /ai/knowledge/group
  -> 后端代码 services/knowledge_service/api.py
```

## 前端接口与后端文件

| 前端文件 | 前端路径 | 后端服务 | 后端代码 |
| --- | --- | --- | --- |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/group` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc/import` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc/import-template` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc/run` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc/stop` | knowledge-service | `services/knowledge_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/mdcontent` | file_service | `services/file_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/knowledge/doc/chunk*` | parser_service | `services/parser_service/api.py` |
| `src/services/knowledge/api.ts` | `/api/v1/ai/embedding/models` | model_service | `services/model_service/api.py` |
| `src/services/upload/api.ts` | `/api/v1/ai/files/upload` | file_service | `services/file_service/api.py` |
| `src/services/chat/api.ts` | `/api/v1/chat/conversations*` | chat_service | `services/chat_service/api.py` |
| `src/services/user/api.ts` | `/api/v1/auth/sso/*` | gateway | `services/gateway/routes/sso.py` |

## 本次已做的兼容处理

`knowledge-web` 与后端历史接口存在少量字段名不一致，已在后端统一兼容：

- 知识库分页：前端 `page_num`，后端原来主要使用 `page_no`。
- 文档列表：前端 `document_name/status/page_num`，后端原来主要使用 `doc_name/state/page_no`。
- 文档删除：前端 `doc_ids`，后端原来主要使用 `document_id`。

以后新增接口时，建议优先保持前后端字段名一致；确实需要兼容旧字段时，把转换逻辑集中写在 API 层，Service 层只接收统一后的字段。

## 建议阅读顺序

1. 看前端：`knowledge-web/src/services/*/api.ts`，确认请求路径和参数。
2. 看网关：`services/gateway/gateway_config.yaml`，确认转到哪个服务。
3. 看服务 API：例如 `services/knowledge_service/api.py`，确认路由函数。
4. 看业务逻辑：例如 `services/knowledge_service/core_services.py`。
5. 看公共模型：`common/models/models.py`。

## 清理说明

仓库中已清理 Python 缓存、系统临时文件、日志和旧备份文件。后续不要提交这些文件；相关规则已在 `.gitignore` 中配置。

## 精简后保留的后端目录

```text
services/gateway            API 网关、SSO、转发
services/knowledge_service  知识库/知识树/文档管理
services/file_service       上传与 Markdown 原文读取
services/model_service      Embedding 模型列表
services/chat_service       对话创建与消息历史查询
services/parser_service     文档切片 chunk 接口
common                      上面服务共享的配置、模型、工具
```

以下旧模块已删除：图谱、媒体处理、流程加工、表格、PageIndex、监控、配置中心、任务执行器、独立 RAG 服务、RAGFlow 适配包、大量测试/报告/Docker 运行数据等。

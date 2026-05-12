# Gateway 精简说明

当前网关只为 `knowledge-web` 转发以下接口：

- `/api/v1/ai/knowledge*` -> `knowledge-service`
- `/api/v1/ai/files/*` -> `file_service`
- `/api/v1/ai/knowledge/mdcontent` -> `file_service`
- `/api/v1/ai/knowledge/doc/chunk*` -> `parser_service`
- `/api/v1/ai/embedding/*` -> `model_service`
- `/api/v1/chat/*` -> `chat_service`
- `/api/v1/auth/sso/*` -> 网关自身 SSO 路由

路由配置见：`gateway_config.yaml`。

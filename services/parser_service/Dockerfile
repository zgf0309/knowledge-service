FROM python:3.10-slim

WORKDIR /app

# 配置国内 apt 镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.list \
    && sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.list \
    || true

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl vim tzdata git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

# 复制服务代码和依赖
COPY services/parser_service/ ./services/parser_service/

# 安装 parser_service 专用依赖 (不含 torch，体积小很多)
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r services/parser_service/requirements.txt

# 复制 common 模块
COPY common/ ./common/

ENV PYTHONPATH=/app
ENV SERVICE_NAME=parser-service
ENV PORT=7110

EXPOSE 7110

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD curl -f http://localhost:7110/health || exit 1

CMD ["uvicorn", "services.parser_service.main:app", "--host", "0.0.0.0", "--port", "7110"]

FROM python:3.10-slim

WORKDIR /app

# 配置国内 apt 镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.list \
    && sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.list \
    || true

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    vim \
    tzdata \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

# Copy requirements first for better caching
COPY common/requirements.txt ./common-requirements.txt

# Install Python dependencies with retry and fallback, disable hash checking
RUN pip install --no-cache-dir --disable-pip-version-check \
    -r common-requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    --retries 10 \
    --timeout 30 || \
    pip install --no-cache-dir --disable-pip-version-check \
    -r common-requirements.txt \
    -i https://pypi.mirrors.ustc.edu.cn/simple/ \
    --trusted-host pypi.mirrors.ustc.edu.cn \
    --retries 10 \
    --timeout 30

# Copy service code
COPY services/ ./services/
COPY common/ ./common/


# Set environment variables
ENV PYTHONPATH=/app
ENV SERVICE_NAME=knowledge-service
ENV PORT=7101

EXPOSE 7101

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:7101/health || exit 1

CMD ["uvicorn", "services.knowledge_service.main:app", "--host", "0.0.0.0", "--port", "7101"]

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies with Aliyun mirrors with Aliyun mirrors
RUN apt-get update && apt-get install -y \
    curl \
    vim \
    tzdata \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

# Copy requirements first for better caching
COPY services/ ./services/
COPY common/requirements.txt ./common-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r common-requirements.txt

# Copy service code
COPY services/ ./services/
COPY common/ ./common/

# Set environment variables
ENV PYTHONPATH=/app
ENV SERVICE_NAME=chat-service
ENV PORT=7105

EXPOSE 7105

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:7105/health || exit 1

CMD ["uvicorn", "services.chat_service.main:app", "--host", "0.0.0.0", "--port", "7105"]

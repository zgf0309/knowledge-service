FROM python:3.10-slim

WORKDIR /app

# Install system dependencies with Aliyun mirrors with Aliyun mirrors
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY services/ ./services/
COPY common/requirements.txt /app/common/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /app/common/requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /app/services/gateway/requirements.txt

# Copy application code
COPY services/ ./services/
COPY common/ /app/common/

# Set working directory
WORKDIR /app/services/gateway

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the application
CMD ["python", "main.py"]

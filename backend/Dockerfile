FROM python:3.13-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
RUN set -eux; \
    pip_args=""; \
    if [ -n "$PIP_INDEX_URL" ]; then pip_args="$pip_args --index-url $PIP_INDEX_URL"; fi; \
    if [ -n "$PIP_TRUSTED_HOST" ]; then pip_args="$pip_args --trusted-host $PIP_TRUSTED_HOST"; fi; \
    pip install --no-cache-dir $pip_args -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

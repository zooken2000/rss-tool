FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非rootユーザーで実行（セキュリティのベストプラクティス）
RUN useradd -m -u 1000 agentcore
USER agentcore

COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/ping || exit 1

CMD ["python", "agent.py"]

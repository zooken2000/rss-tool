FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非rootユーザーで実行（セキュリティのベストプラクティス）
RUN useradd -m -u 1000 agentcore
USER agentcore

COPY . .

EXPOSE 8080

# AgentCore Observability（ADOT による自動計装）
# OTEL エクスポーター先は AgentCore Runtime が実行時に自動設定する
ENV AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator \
    OTEL_RESOURCE_ATTRIBUTES=service.name=aws-digest-agent \
    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true \
    OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=http,sqlalchemy,psycopg2,pymysql,sqlite3,aiopg,asyncpg,mysql_connector,urllib3,requests,system_metrics,google-genai

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/ping || exit 1

CMD ["opentelemetry-instrument", "python", "agent.py"]

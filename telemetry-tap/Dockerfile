# telemetry-tap — MAVLink subscriber → NDJSON for SOC ingest
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul

RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata && \
    rm -rf /var/lib/apt/lists/* && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tap.py .
COPY ground_truth_tap.py .

# 기본은 relay-path tap. ground-truth-tap 배포는 k8s command override로
# ground_truth_tap.py 를 대신 실행(같은 이미지 재사용, 이진 중복 없음).
ENTRYPOINT ["python", "-u", "tap.py"]

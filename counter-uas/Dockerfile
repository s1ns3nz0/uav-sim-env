# counter-uas — 카운터 드론 RF 탐지→근접→자동재밍 시뮬(FastAPI).
# 송신 없음: 재밍은 J/S 효과로 시뮬레이션만 한다. NDJSON → UAVCounterUas_CL.
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

COPY app.py .
COPY counter_uas ./counter_uas

EXPOSE 8810
ENTRYPOINT ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8810"]

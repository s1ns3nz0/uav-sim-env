# datalink-satcom — BLOS SATCOM link emulation + integrity tagging (FastAPI).
# Phase B (tagging-first): models link/session/seq/RTT/jam metadata for S3.
# The OpenSAND DVB-S2/RCS2 physical-layer (ST/SAT/GW) is layered in afterwards.
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

EXPOSE 8800
ENTRYPOINT ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8800"]

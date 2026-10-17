# Atif Assistant — web deployment (Hugging Face Spaces / any Docker host).
#
# No native models in this image: the hosted version talks to cloud providers
# (keys via env/Secrets) and uses the browser's speech API. The Mac and
# Android builds add on-device llama.cpp/whisper.cpp on top of this same code.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first for layer caching. requirements.lock is the exact set
# proven green by the 429-test suite.
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY atif_assistant ./atif_assistant
COPY web ./web

# /data is where Hugging Face's optional persistent storage mounts; without
# it the directory is ephemeral and memory resets on redeploy (export with
# GET /api/backup).
ENV ATIF_ASSISTANT_DATA_DIR=/data \
    ATIF_ASSISTANT_HOST=0.0.0.0 \
    ATIF_ASSISTANT_PORT=7860 \
    ATIF_ASSISTANT_COMMIT=dev

RUN mkdir -p /data
EXPOSE 7860

CMD ["uvicorn", "atif_assistant.app:app", "--host", "0.0.0.0", "--port", "7860"]

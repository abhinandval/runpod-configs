# syntax=docker/dockerfile:1

# Official llama.cpp server-cuda image, pinned to the linux/amd64 manifest
# digest. It contains llama-server and the CUDA-enabled llama.cpp libraries.
ARG LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:7f87a3bbe3143cdb857f5c84f82d2c15528be70ca0e7c5ade9a47d56b791f93f

FROM ${LLAMA_CPP_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_CACHE_DIR=/models \
    LLAMA_CACHE=/models \
    LLAMA_SERVER_BIN=/app/llama-server \
    LD_LIBRARY_PATH=/app:/usr/local/cuda/lib64 \
    SERVER_HOST=127.0.0.1 \
    SERVER_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
       python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && test -x /app/llama-server

COPY requirements.txt /opt/app/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /opt/app/requirements.txt

WORKDIR /opt/app
COPY src /opt/app/src

# Model downloads and the llama.cpp cache live on ephemeral container disk.
# New workers will redownload the model.
RUN mkdir -p /models

ENTRYPOINT ["python3", "-m", "src.main"]

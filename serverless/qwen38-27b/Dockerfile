# syntax=docker/dockerfile:1

# This revision is known to support the Qwen3.8 GGUF architecture. Override it
# only after validating the new revision against the selected model.
ARG CUDA_IMAGE=nvidia/cuda:12.4.1-devel-ubuntu22.04
ARG LLAMA_CPP_REF=5f754ea0e2fd21e1213db7ebebfd65d938d9d69c
ARG CMAKE_BUILD_PARALLEL_LEVEL=1

FROM ${CUDA_IMAGE} AS builder
ARG LLAMA_CPP_REF
ARG CUDA_ARCHITECTURES="86;89"
ARG CMAKE_BUILD_PARALLEL_LEVEL

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       cmake \
       build-essential \
       git \
       libcurl4-openssl-dev \
       libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
# The server image uses Hugging Face references, so keep curl support enabled.
# Keep the CPU backend portable under Apple Silicon/QEMU emulation. The CUDA
# backend and its target architectures remain enabled for native RunPod builds.
RUN git clone https://github.com/ggml-org/llama.cpp.git \
    && cd llama.cpp \
    && git checkout "${LLAMA_CPP_REF}" \
    && test "${CMAKE_BUILD_PARALLEL_LEVEL}" -ge 1 \
    && cmake -S . -B build \
       -DGGML_CUDA=ON \
       -DGGML_NATIVE=OFF \
       -DGGML_CPU_ARCH=x86-64 \
       -DLLAMA_CURL=ON \
       -DBUILD_SHARED_LIBS=ON \
       -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
       -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --config Release --target llama-server -j"${CMAKE_BUILD_PARALLEL_LEVEL}" \
    && cmake --install build --prefix /opt/llama.cpp \
    && install -d /opt/llama.cpp/bin /opt/llama.cpp/lib \
    && test -x /opt/llama.cpp/bin/llama-server \
    && find build \( -type f -o -type l \) -name 'lib*.so*' \
       -exec cp -a {} /opt/llama.cpp/lib/ \; \
    && test -n "$(find /opt/llama.cpp/lib -maxdepth 1 -name 'libllama.so*' -print -quit)" \
    && test -n "$(find /opt/llama.cpp/lib -maxdepth 1 -name 'libggml.so*' -print -quit)" \
    && test -n "$(find /opt/llama.cpp/lib -maxdepth 1 -name 'libggml-cuda.so*' -print -quit)" \
    && export LD_LIBRARY_PATH="/opt/llama.cpp/lib:/opt/llama.cpp/bin:/usr/local/cuda/lib64" \
    && ! ldd /opt/llama.cpp/bin/llama-server | grep -q 'not found'

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_CACHE_DIR=/models \
    LLAMA_CACHE=/models \
    LLAMA_SERVER_BIN=/opt/llama.cpp/bin/llama-server \
    LD_LIBRARY_PATH=/opt/llama.cpp/lib:/opt/llama.cpp/bin:/usr/local/cuda/lib64 \
    SERVER_HOST=127.0.0.1 \
    SERVER_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       libcurl4 \
       libgomp1 \
       libstdc++6 \
       python3 \
       python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/llama.cpp/ /opt/llama.cpp/
COPY requirements.txt /opt/app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /opt/app/requirements.txt

WORKDIR /opt/app
COPY src /opt/app/src

# Model downloads and the llama.cpp cache live on ephemeral container disk.
# New workers will redownload the model.
RUN mkdir -p /models

ENTRYPOINT ["python3", "-m", "src.main"]

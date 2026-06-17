# syntax=docker/dockerfile:1.7
FROM docker.io/nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

ARG FACEFUSION_COMFYUI_COMMIT=3e738296393d57b5070a59a0cba082faabfccde8

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FACEFUSION_DISABLE_MODEL_DOWNLOADS=1 \
    FACEFUSION_PRELOAD_MODELS=1 \
    FACEFUSION_DEFAULT_PRESET=hyperswap_1a_512 \
    FACEFUSION_REQUIRED_MODELS=hyperswap_1a_256.onnx,scrfd_2.5g.onnx,arcface_w600k_r50.onnx \
    FACEFUSION_MODEL_DIRS=/runpod-volume/huggingface-cache/hub:/runpod-volume/models/facefusion:/runpod-volume/models:/workspace/models/facefusion:/workspace/models:/opt/Facefusion_comfyui/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        python3-pip \
        python3.12 \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install \
        httpx \
        httpx-retries \
        numpy \
        onnx \
        onnxruntime-gpu==1.20.1 \
        opencv-python-headless \
        pillow \
        runpod

WORKDIR /opt
RUN git clone https://github.com/huygiatrng/Facefusion_comfyui.git /opt/Facefusion_comfyui \
    && cd /opt/Facefusion_comfyui \
    && git checkout "${FACEFUSION_COMFYUI_COMMIT}"

COPY patch_facefusion_no_downloads.py /opt/patch_facefusion_no_downloads.py
RUN python /opt/patch_facefusion_no_downloads.py /opt/Facefusion_comfyui

ENV PYTHONPATH=/opt/Facefusion_comfyui

WORKDIR /app
COPY model_preflight.py handler.py /app/

CMD ["python", "-u", "handler.py"]

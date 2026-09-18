# MinerU GPU API image. Build args select the machine profile
# (see infra/mineru/{low,medium,high}.env).
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ARG MINERU_EXTRAS=pipeline

# cu128 torch only when the base image does not already ship it (vLLM does).
RUN python -c "import torch" 2>/dev/null \
    || pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cu128

RUN pip install --no-cache-dir "mineru[${MINERU_EXTRAS}]>=3.4,<3.5"

# Undeclared OCR dep (pytorchocr/imaug operators).
RUN pip install --no-cache-dir six

# OpenCV (pulled by mineru) needs these shared libs on slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]

#!/bin/bash
# EC2 user-data for the GPU INFERENCE instance (g4dn.xlarge, spot).
#
# IMPORTANT: launch this instance with the AWS Deep Learning AMI (DLAMI) —
# search "Deep Learning OSS Nvidia Driver AMI" in the AMI picker. It ships
# with the NVIDIA driver, Docker, and the NVIDIA container toolkit already
# installed and working together, which is the single biggest source of
# pain in a from-scratch GPU Docker setup. Do not use a plain Amazon Linux
# AMI here — you would need to install and version-match the driver,
# container toolkit, and CUDA runtime by hand.
#
# What it does:
#   1. Pulls the vLLM OpenAI-compatible server image.
#   2. Starts it serving Qwen2.5-VL-7B-Instruct-AWQ on port 8000, with
#      --gpu-memory-utilization tuned for a single T4's 16 GB.
#   3. Restarts automatically on crash or instance reboot.
#
# This deliberately listens on 0.0.0.0:8000 with NO auth — network access
# must be restricted at the security-group level to only the app tier's
# security group (see infra/scripts/provision-aws.sh). Do not give this
# instance a public IP with port 8000 open to 0.0.0.0/0.

set -euxo pipefail

# DLAMI ships Docker + nvidia-container-toolkit already configured; this is
# just a safety net in case a different AMI is used.
if ! command -v docker &> /dev/null; then
    dnf install -y docker || apt-get update && apt-get install -y docker.io
    systemctl enable --now docker
fi

docker rm -f qwen-vlm 2>/dev/null || true

docker run -d \
    --name qwen-vlm \
    --restart unless-stopped \
    --gpus all \
    --shm-size 8g \
    -p 8000:8000 \
    -v /opt/vllm-cache:/root/.cache/huggingface \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-VL-7B-Instruct-AWQ \
    --quantization awq \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.90 \
    --host 0.0.0.0 \
    --port 8000

# First start downloads ~5-6 GB of model weights from Hugging Face — expect
# several minutes before /v1/models responds. Check progress with:
#   docker logs -f qwen-vlm

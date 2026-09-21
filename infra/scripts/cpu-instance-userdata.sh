#!/bin/bash
# EC2 user-data for the CPU INFERENCE CONTINGENCY instance (t3.large,
# on-demand or spot). Use this instead of gpu-instance-userdata.sh if the
# GPU vCPU quota request (see docs/DEPLOY.md Phase 0) is rejected or still
# pending — it needs no quota increase at all, since t3 is a standard
# instance family every account can launch by default.
#
# What it does: runs llama.cpp's OpenAI-compatible server with
# Qwen2.5-VL-3B-Instruct at 4-bit quantization. Expect roughly 30-90s per
# card rather than the GPU path's 2-5s — fine for correctness testing and
# small batches, painful for a large live demo batch.

set -euxo pipefail

dnf update -y
dnf install -y docker
systemctl enable --now docker

docker rm -f qwen-vlm-cpu 2>/dev/null || true

# The ghcr.io/ggml-org/llama.cpp:server image bakes in its own HEALTHCHECK
# against the default port 8080 — since we run on 8000 (LLAMA_ARG_PORT
# below, to match VLM_PRIMARY_BASE_URL), that default check always fails
# and `docker ps` misreports the container as unhealthy even when it's
# serving real requests correctly. Overriding it here to check the actual
# port fixes that (found during deployment testing — see git history).
docker run -d \
    --name qwen-vlm-cpu \
    --restart unless-stopped \
    --shm-size 4g \
    -p 8000:8000 \
    -v /opt/llama-models:/models \
    --health-cmd "curl -f http://localhost:8000/health || exit 1" \
    --health-interval 30s --health-timeout 5s --health-retries 3 --health-start-period 15s \
    -e LLAMA_ARG_HF_REPO="ggml-org/Qwen2.5-VL-3B-Instruct-GGUF" \
    -e LLAMA_ARG_HF_FILE="Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf" \
    -e LLAMA_ARG_MMPROJ_URL="https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf" \
    -e LLAMA_ARG_CTX_SIZE="4096" \
    -e LLAMA_ARG_THREADS="2" \
    -e LLAMA_ARG_HOST="0.0.0.0" \
    -e LLAMA_ARG_PORT="8000" \
    ghcr.io/ggml-org/llama.cpp:server

# Same no-public-exposure rule as the GPU instance: restrict inbound :8000
# to the app tier's security group only.
#
# On the app instance, point VLM_PRIMARY_MODEL at whatever this server
# actually reports — check with `curl http://<this-instance>:8000/v1/models`
# — instead of the AWQ model name used for the GPU path.

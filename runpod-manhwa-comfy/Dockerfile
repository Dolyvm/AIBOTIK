FROM runpod/worker-comfyui:5.8.5-base

WORKDIR /comfyui

RUN mkdir -p models/checkpoints models/loras

RUN wget \
  --tries=10 \
  --timeout=60 \
  --read-timeout=300 \
  --waitretry=10 \
  --header="User-Agent: Mozilla/5.0" \
  -O models/checkpoints/wai_illustrious_v16.safetensors \
  "https://civitai.com/api/download/models/2514310?type=Model&format=SafeTensor"

RUN wget \
  --tries=10 \
  --timeout=60 \
  --read-timeout=300 \
  --waitretry=10 \
  --header="User-Agent: Mozilla/5.0" \
  -O models/loras/niji_semi_realism_v4.safetensors \
  "https://civitai.com/api/download/models/2854725?type=Model&format=SafeTensor"

RUN wget \
  --tries=10 \
  --timeout=60 \
  --read-timeout=300 \
  --waitretry=10 \
  --header="User-Agent: Mozilla/5.0" \
  -O models/loras/semi_realistic_anime_men.safetensors \
  "https://civitai.com/api/download/models/1670886?type=Model&format=SafeTensor"

RUN ls -lh models/checkpoints models/loras

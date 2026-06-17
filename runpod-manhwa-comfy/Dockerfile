FROM runpod/worker-comfyui:5.8.5-base

WORKDIR /comfyui

# No checkpoint/LoRA downloads here. Mount them through RunPod Cached Models
# or Network Volume so user jobs never pay for model downloads.
COPY custom_nodes/model_preflight /comfyui/custom_nodes/model_preflight
COPY start-manhwa.sh /start-manhwa.sh
RUN chmod +x /start-manhwa.sh

ENV MANHWA_REQUIRED_CHECKPOINTS="wai_illustrious_v16.safetensors"
ENV MANHWA_REQUIRED_LORAS="niji_semi_realism_v4.safetensors,semi_realistic_anime_men.safetensors"

CMD ["/start-manhwa.sh"]

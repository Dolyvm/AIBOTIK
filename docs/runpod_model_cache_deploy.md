# RunPod FaceSwap/Manhwa Deploy Notes

## Цель

Docker image должен содержать только worker code. FaceSwap больше не использует
ComfyUI worker base, потому что `runpod/worker-comfyui:5.8.5-base` содержит
слой около 9.57 GB. Manhwa остается ComfyUI worker, потому что ему нужен ComfyUI
workflow. Большие модели должны быть заранее размещены в RunPod Cached Models и
смонтированы до старта worker.

Это убирает две старые проблемы:

- модели не скачиваются внутри user job на оплачиваемом GPU-времени;
- Docker Hub не получает гигабайтные model layers, из-за которых `docker buildx --push` падал через 30-50 минут.

Если Network Volume режет доступность дешевых GPU в нужных дата-центрах, используем Cached Models:

- складываем все нужные файлы одного endpoint в один Hugging Face repository;
- в RunPod endpoint оставляем Network Volumes пустым;
- в поле Model указываем этот Hugging Face repository;
- worker ищет файлы в `/runpod-volume/huggingface-cache/hub` и падает на startup, если модели не пришли.

Это не привязывает endpoint к дата-центру Network Volume и не скачивает модели внутри user job.

## FaceSwap endpoint

Endpoint: `nif211wfdmdmc5`

App contract:

- `RUNPOD_FACE_SWAP_ENDPOINT_ID=nif211wfdmdmc5`
- app provider timeout: `330s`
- request policy `executionTimeout=300000`
- request policy `ttl=600000`
- ARQ timeout: `600s`
- frontend polling budget: `420s`

RunPod endpoint settings:

- `workersMin=0`
- `workersMax=1` initially
- `idleTimeout=300`
- `executionTimeoutMs=300000`

`idleTimeout=300` keeps one worker warm for about 5 minutes after a successful generation. After that it must scale to zero. If billing shows a pod running for hours, use RunPod console to stop/disable the endpoint and open support with endpoint id, pod id, billing rows, and config.

Required mounted/cache models:

- `hyperswap_1a_256.onnx`
- `scrfd_2.5g.onnx`
- `arcface_w600k_r50.onnx`

The FaceSwap worker image in `runpod-facefusion-direct/` is a direct ONNX worker
based on `docker.io/nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04`. It pins the
FaceFusion ONNX implementation at commit
`3e738296393d57b5070a59a0cba082faabfccde8`, disables runtime model downloads,
and fails startup if Cached Models are missing or ONNXRuntime cannot expose
`CUDAExecutionProvider`.

Build it as a new repository/tag so it cannot accidentally inherit the old
ComfyUI layers:

```bash
docker buildx build \
  --platform linux/amd64 \
  -t docker.io/dolyvm/runpod-facefusion-direct-worker:0.5.0 \
  --push \
  runpod-facefusion-direct
```

The new image may still download CUDA and Python wheels during the first build,
but it must not pull or push the old ComfyUI layer
`sha256:45c936917990c548cc6c2d083138a7aebb29878cdcbea90f669312d1cade4759`.
After pushing, inspect the manifest before switching the RunPod endpoint.

Fallback without Network Volume: create one Hugging Face repo with these files and set RunPod endpoint `Model` to that repo. Do not attach a Network Volume.

## Manhwa endpoint

Endpoint: `p986xr9nxchgux`

App contract:

- `RUNPOD_MANHWA_ENDPOINT_ID=p986xr9nxchgux`
- app timeout: `900s`
- app queue timeout: `180s` via `RUNPOD_MANHWA_QUEUE_TIMEOUT_SECONDS`
- request policy `executionTimeout=900000`
- request policy `ttl=1200000`

Required mounted/cache models:

- checkpoint: `wai_illustrious_v16.safetensors`
- LoRA: `niji_semi_realism_v4.safetensors`
- LoRA: `semi_realistic_anime_men.safetensors`

The Manhwa worker image in `runpod-manhwa-comfy/` also has no model download step.
Its startup wrapper runs preflight before `/start.sh`. It fails startup if the
checkpoint or LoRA files are absent, and symlinks Cached Models into
`/comfyui/models/checkpoints` and `/comfyui/models/loras` before ComfyUI validates
any workflow.

Fallback without Network Volume: create one Hugging Face repo with the checkpoint and both LoRA files, then set RunPod endpoint `Model` to that repo. Do not attach a Network Volume.

Build and push a small overlay tag into the existing `dolyvm/manhwa` repository,
where the old heavy ComfyUI layer already exists:

```bash
docker buildx build \
  --platform linux/amd64 \
  -t docker.io/dolyvm/manhwa:cached-0.1.2 \
  --push \
  runpod-manhwa-comfy
```

After switching endpoint `p986xr9nxchgux` to `docker.io/dolyvm/manhwa:cached-0.1.2`,
the worker logs must contain these startup markers:

- `Manhwa startup wrapper started`
- `Manhwa models preflight passed`
- `Manhwa model preflight completed`
- `Manhwa starting worker command: /start.sh`
- `model ready`

If logs only show `model ready` and workflow validation still says
`ckpt_name ... not in []`, the endpoint is still running an older tag, the logs
are truncated, or the Cached Model repo is not attached to that endpoint.

Before sending user traffic, purge old pending jobs and inspect endpoint health:

```bash
curl -X POST \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/p986xr9nxchgux/purge-queue"

curl -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/p986xr9nxchgux/health"
```

The clean baseline is `jobs.inQueue=0` and no unexpected `jobs.inProgress`.

Smoke the queue/worker registration path with a minimal console or API request
that uses the worker-comfyui contract:

```json
{
  "input": {
    "workflow": {
      "...": "paste the API workflow generated by the app or ComfyUI"
    }
  }
}
```

Then check `/status/{job_id}` until the job moves through
`IN_QUEUE -> IN_PROGRESS -> COMPLETED`, and call `/health` again. If the job
stays `IN_QUEUE` while RunPod shows a running worker with no GPU/CPU activity,
debug endpoint/worker registration before increasing `workersMax`.

After this ComfyUI worker is stable, the next latency/cold-start project is a
direct PyTorch/Diffusers Manhwa worker. Cached Models remove runtime model
downloads, but they do not remove the heavy `runpod/worker-comfyui` runtime
image from cold starts.

## Smoke checks after deploy

Check worker logs before sending real traffic:

- `FaceFusion models preflight passed` or `Manhwa models preflight passed`
- no line like `Model hyperswap_1a_256.onnx not found, downloading`
- no Civitai/GitHub model download during a user request

Check the FaceSwap image manifest:

- no layer digest `sha256:45c936917990c548cc6c2d083138a7aebb29878cdcbea90f669312d1cade4759`

Check app logs during a forced timeout/cancel:

- local job records `runpod_jobs` in `request_payload`
- app logs `RunPod cancel requested`
- RunPod job reaches `CANCELLED` or another terminal state
- for Manhwa queue stalls, app logs `RunPod queue timeout` and cancels with
  reason `queue_timeout`

Check billing after smoke:

- worker stays warm for roughly 300 seconds after success;
- after that the endpoint scales to zero;
- no pod remains billed for hours.

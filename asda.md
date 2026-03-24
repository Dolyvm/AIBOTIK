# Fix: Frontend volume not updating + missing images

## Context
Two related problems:
1. **Root cause:** Named Docker volume `frontend_dist` never updates on rebuild — Docker preserves old data in named volumes. This is why we had to delete the volume manually, which cascaded into losing `generated_images`.
2. **Symptoms:** Lost world cover images, broken character avatar paths.

## Plan

### Step 1: Fix frontend deployment (root cause)

**Problem:** `frontend` container builds dist into `/dist`, shared via named volume `frontend_dist` to nginx. Named volumes only populate on first create — subsequent rebuilds don't overwrite.

**Fix:** Change frontend container to copy fresh files into the volume on every start.

**File:** `frontend/Dockerfile` (on server — `/root/AIBOTIK/frontend/Dockerfile`)

Replace `CMD ["sleep", "infinity"]` with a startup script that:
1. Clears old files from the volume mount point
2. Copies fresh build output
3. Sleeps to keep container alive

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM busybox:stable-musl
COPY --from=builder /app/dist /app/dist
CMD ["sh", "-c", "rm -rf /dist/* && cp -r /app/dist/* /dist/ && sleep infinity"]
```

Key change: build output goes to `/app/dist` (inside image), then gets copied to `/dist` (volume mount) at runtime. This way every container restart gets fresh files.

### Step 2: Fix Sukuna avatar path in DB
```sql
UPDATE characters SET visual_data = jsonb_set(visual_data, '{avatar}', '"/images/avatars/sukuna_test.png"')
WHERE id = 'sukuna_test';
```
The file exists at `/data/images/avatars/sukuna_test.png` in nginx.

### Step 3: Set lost world covers to NULL
3 custom world covers were lost when volume was deleted. Set to NULL so frontend shows a placeholder:
```sql
UPDATE worlds SET cover_image = NULL
WHERE cover_image LIKE '%/images/world_covers/%';
```

## Files to modify
- `/root/AIBOTIK/frontend/Dockerfile` (on server, and locally for consistency)

## Verification
1. `docker compose down && docker compose up -d --build` — frontend should update WITHOUT deleting any volumes
2. Sukuna avatar loads
3. Worlds without covers show placeholder gracefully
4. All other images still work

#!/bin/sh
set -eu

echo "Manhwa startup wrapper started"
python /comfyui/custom_nodes/model_preflight/preflight.py
echo "Manhwa model preflight completed"

if [ "$#" -eq 0 ]; then
    set -- /start.sh
fi

echo "Manhwa starting worker command: $*"
exec "$@"

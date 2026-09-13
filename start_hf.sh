#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Sky Eco-Travel Advisor — HuggingFace Spaces startup script
# Starts: Action Server → Rasa Server → nginx (port 7860)
# ══════════════════════════════════════════════════════════════

echo "=== Sky Eco-Travel Advisor — Starting services ==="

# Export API keys from HF Secrets (set in Space settings)
export CLIMATIQ_API_KEY="${CLIMATIQ_API_KEY:-not_set}"
export ORS_API_KEY="${ORS_API_KEY:-not_set}"

# 1. Start action server in background
echo "[1/3] Starting Rasa Action Server on port 5055..."
rasa run actions --port 5055 &
ACTION_PID=$!
sleep 3

# 2. Start Rasa server in background
echo "[2/3] Starting Rasa Server on port 5005..."
rasa run \
  --enable-api \
  --cors "*" \
  --port 5005 \
  --debug &
RASA_PID=$!

# Wait for Rasa to load the model
echo "    Waiting for Rasa to load model..."
for i in $(seq 1 60); do
  if curl -s http://127.0.0.1:5005/ > /dev/null 2>&1; then
    echo "    Rasa is ready!"
    break
  fi
  sleep 2
done

# 3. Start nginx (foreground to keep container alive)
echo "[3/3] Starting nginx on port 7860..."
nginx -g "daemon off;"

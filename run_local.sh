#!/usr/bin/env bash
# run_local.sh — start all services locally (no Docker required)
# Usage:  bash run_local.sh
# Stop:   Ctrl+C  (kills all background processes)

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── install deps if needed ────────────────────────────────────────────────────
if ! python -c "import fastapi" 2>/dev/null; then
  echo "📦 Installing dependencies..."
  pip install -r requirements.txt -q
fi

echo ""
echo "🚀 Starting mock services..."
echo "   Auth  → http://localhost:9001"
echo "   Chat  → http://localhost:9002"
echo "   AI    → http://localhost:9003"
echo ""

python -m services.auth_service.main &
PID_AUTH=$!

python -m services.chat_service.main &
PID_CHAT=$!

python -m services.ai_service.main &
PID_AI=$!

# Give services a moment to bind
sleep 1

echo "🌐 Starting gateway → http://localhost:8000"
echo ""
echo "   Try:"
echo "   curl http://localhost:8000/health"
echo "   curl http://localhost:8000/auth/health"
echo "   curl http://localhost:8000/chat/rooms"
echo "   curl http://localhost:8000/ai/models"
echo "   curl http://localhost:8000/gateway/routes"
echo ""

# Run gateway in foreground so Ctrl+C kills it
python -m uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload

# Cleanup background services on exit
trap "kill $PID_AUTH $PID_CHAT $PID_AI 2>/dev/null; echo 'Services stopped.'" EXIT

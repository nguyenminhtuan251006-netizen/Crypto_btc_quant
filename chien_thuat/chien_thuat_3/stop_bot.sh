#!/bin/bash
# ==============================================================================
# Script Dừng Bot Chạy Ngầm
# ==============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname "$(dirname "$DIR")")"
PID_FILE="$WORKSPACE_DIR/logs/bot.pid"

if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if ps -p "$BOT_PID" > /dev/null 2>&1; then
        echo "🛑 Đang dừng bot (PID: $BOT_PID)..."
        kill "$BOT_PID"
        sleep 1
        if ps -p "$BOT_PID" > /dev/null 2>&1; then
            kill -9 "$BOT_PID"
        fi
        rm -f "$PID_FILE"
        echo "✅ Đã dừng bot thành công."
        exit 0
    else
        echo "ℹ️  Tiến trình PID $BOT_PID không còn chạy."
        rm -f "$PID_FILE"
    fi
fi

# Fallback tìm kiếm bằng tên process
PIDS=$(pgrep -f "live_trader_demo.py --loop")
if [ -n "$PIDS" ]; then
    echo "🛑 Đang dừng tiến trình: $PIDS"
    kill $PIDS
    echo "✅ Đã dừng bot thành công."
else
    echo "ℹ️  Hiện không có bot nào đang chạy."
fi

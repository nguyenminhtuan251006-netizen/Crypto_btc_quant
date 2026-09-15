#!/bin/bash
# ==============================================================================
# Script Khởi Động Bot Chạy Ngầm 24/7 (Bất chấp tắt máy / tắt trình duyệt)
# ==============================================================================
# Sử dụng nohup để tiến trình độc lập với terminal/session SSH của bạn.
# Dù bạn tắt nguồn máy tính cá nhân, server vẫn chạy bot liên tục 24/7.
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname "$(dirname "$DIR")")"
PYTHON_BIN="/home/tuannm/.venv/bin/python"
LOG_FILE="$WORKSPACE_DIR/logs/hft_live_trader.log"
PID_FILE="$WORKSPACE_DIR/logs/bot.pid"

mkdir -p "$WORKSPACE_DIR/logs"

# Kiểm tra xem bot đã chạy chưa
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "⚠️  Bot đang chạy rồi! (PID: $OLD_PID)"
        echo "   Xem log: tail -f $LOG_FILE"
        echo "   Dừng bot: ./chien_thuat/chien_thuat_3/stop_bot.sh"
        exit 0
    fi
fi

echo "================================================================================"
echo "  🚀 KHỞI ĐỘNG BOT CHIẾN THUẬT 3 CHẠY NGẦM ĐỘC LẬP TRÊN SERVER"
echo "================================================================================"
echo "  • Phiên bản: HFT Microstructure V2 (Oxford Paper)"
echo "  • Server: Ubuntu Linux (Đang hoạt động độc lập)"
echo "  • File nhật ký: $LOG_FILE"
echo "  • Lưu ý: Bạn có thể tắt nguồn máy tính / ngắt mạng, bot vẫn chạy ngầm trên Server."
echo "================================================================================"

# Chạy với nohup trong nền
nohup "$PYTHON_BIN" "$DIR/live_trader_demo.py" --loop >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

sleep 1
if ps -p "$BOT_PID" > /dev/null 2>&1; then
    echo "✅ Bot đã khởi động thành công với PID: $BOT_PID"
    echo "   • Lệnh xem nhật ký realtime: tail -f $LOG_FILE"
    echo "   • Lệnh dừng bot: ./chien_thuat/chien_thuat_3/stop_bot.sh"
else
    echo "❌ Có lỗi xảy ra khi khởi động bot. Kiểm tra $LOG_FILE"
fi

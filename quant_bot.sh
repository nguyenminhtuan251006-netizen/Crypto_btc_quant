#!/bin/bash
# ==============================================================================
# BỘ ĐIỀU KHIỂN HỆ THỐNG TRADING BOT 24/7 (CRYPTO BTC QUANT LAB)
# ==============================================================================
# Chạy độc lập ngầm trên Linux Server. 
# Kể cả khi bạn tắt máy tính, tắt wifi hay đi ngủ, bot vẫn tự động vận hành 24/7.
#
# Cách sử dụng:
#   ./quant_bot.sh start [tên_chiến_thuật]   (Mặc định: chien_thuat_3)
#   ./quant_bot.sh stop                     (Dừng bot đang chạy)
#   ./quant_bot.sh status                   (Xem trạng thái bot và vị thế)
#   ./quant_bot.sh logs [tên_chiến_thuật]    (Xem nhật ký realtime)
#   ./quant_bot.sh list                     (Xem danh sách các chiến thuật)
#   ./quant_bot.sh restart [tên_chiến_thuật]
# ==============================================================================

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/home/tuannm/.venv/bin/python"
PID_FILE="$WORKSPACE_DIR/logs/daemon.pid"
NAME_FILE="$WORKSPACE_DIR/logs/active_strategy.txt"
LOG_DIR="$WORKSPACE_DIR/logs"

mkdir -p "$LOG_DIR"

COMMAND="$1"
STRATEGY="${2:-chien_thuat_3}"

if [ -f "$NAME_FILE" ] && [ -z "$2" ]; then
    STRATEGY=$(cat "$NAME_FILE")
fi

LOG_FILE="$LOG_DIR/live_${STRATEGY}.log"

case "$COMMAND" in
    start)
        if [ -f "$PID_FILE" ]; then
            OLD_PID=$(cat "$PID_FILE")
            if ps -p "$OLD_PID" > /dev/null 2>&1; then
                ACTIVE_STRAT="unknown"
                [ -f "$NAME_FILE" ] && ACTIVE_STRAT=$(cat "$NAME_FILE")
                echo "⚠️  Hệ thống đang có bot chạy ngầm rồi!"
                echo "   • Chiến thuật: $ACTIVE_STRAT (PID: $OLD_PID)"
                echo "   • Xem nhật ký: ./quant_bot.sh logs"
                echo "   • Dừng bot:    ./quant_bot.sh stop"
                exit 0
            fi
        fi

        echo "================================================================================"
        echo "  🚀 KHỞI ĐỘNG HỆ THỐNG TRADING BOT CHẠY NGẦM 24/7 TRÊN SERVER"
        echo "================================================================================"
        echo "  • Chiến thuật nạp: $STRATEGY"
        echo "  • Máy chủ: Ubuntu Linux (Hoạt động độc lập 24/7)"
        echo "  • File nhật ký: $LOG_FILE"
        echo "  • Lưu ý: Bạn có thể tắt nguồn máy tính / tắt app, bot vẫn tự chạy trên Server."
        echo "================================================================================"

        echo "$STRATEGY" > "$NAME_FILE"
        nohup env PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u "$WORKSPACE_DIR/execution/daemon.py" --strategy "$STRATEGY" >> "$LOG_FILE" 2>&1 &
        BOT_PID=$!
        echo "$BOT_PID" > "$PID_FILE"

        sleep 1.5
        if ps -p "$BOT_PID" > /dev/null 2>&1; then
            echo "✅ Bot đã kích hoạt thành công! (PID: $BOT_PID)"
            echo "   • Lệnh xem nhật ký:  ./quant_bot.sh logs"
            echo "   • Lệnh kiểm tra:     ./quant_bot.sh status"
            echo "   • Lệnh dừng bot:     ./quant_bot.sh stop"
        else
            echo "❌ Không thể khởi động bot. Vui lòng kiểm tra file: $LOG_FILE"
        fi
        ;;

    stop)
        STOPPED=0
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
                STOPPED=1
            fi
        fi

        # Fallback quét theo process
        PIDS=$(pgrep -f "execution/daemon.py")
        if [ -n "$PIDS" ]; then
            echo "🛑 Đang dừng các tiến trình liên quan: $PIDS"
            kill $PIDS
            echo "✅ Đã dừng toàn bộ bot."
            STOPPED=1
        fi

        # Dừng cả script cũ nếu còn
        OLD_PIDS=$(pgrep -f "live_trader_demo.py --loop")
        if [ -n "$OLD_PIDS" ]; then
            kill $OLD_PIDS
            STOPPED=1
        fi

        if [ $STOPPED -eq 0 ]; then
            echo "ℹ️  Hiện không có bot nào đang chạy."
        fi
        ;;

    status)
        echo "================================================================================"
        echo "             📊 TRẠNG THÁI HỆ THỐNG TRADING BOT CHẠY NGẦM"
        echo "================================================================================"
        RUNNING=0
        if [ -f "$PID_FILE" ]; then
            BOT_PID=$(cat "$PID_FILE")
            if ps -p "$BOT_PID" > /dev/null 2>&1; then
                ACTIVE_STRAT=$(cat "$NAME_FILE" 2>/dev/null || echo "chien_thuat_3")
                UPTIME=$(ps -p "$BOT_PID" -o etime= | tr -d ' ')
                MEM=$(ps -p "$BOT_PID" -o rss= | awk '{printf "%.1f MB", $1/1024}')
                echo "  🟢 TRẠNG THÁI: ĐANG CHẠY NGẦM (ACTIVE 24/7)"
                echo "  • Tiến trình (PID):    $BOT_PID"
                echo "  • Chiến thuật chạy:    $ACTIVE_STRAT"
                echo "  • Thời gian chạy liên tục: $UPTIME"
                echo "  • Bộ nhớ tiêu thụ:     $MEM"
                echo "  • File nhật ký:        $LOG_FILE"
                RUNNING=1
            fi
        fi

        if [ $RUNNING -eq 0 ]; then
            echo "  ⚪ TRẠNG THÁI: ĐANG DỪNG (INACTIVE)"
            echo "  • Khởi động bot bằng: ./quant_bot.sh start [tên_chiến_thuật]"
        fi

        echo "--------------------------------------------------------------------------------"
        echo "  [Nhật ký 5 lượt gần nhất]:"
        if [ -f "$LOG_FILE" ]; then
            tail -n 5 "$LOG_FILE" | sed 's/^/    /'
        else
            echo "    (Chưa có nhật ký)"
        fi
        echo "================================================================================"
        ;;

    logs)
        if [ -f "$LOG_FILE" ]; then
            echo "👀 Đang theo dõi nhật ký realtime của '$STRATEGY' (Bấm Ctrl+C để thoát)..."
            tail -f "$LOG_FILE"
        else
            echo "⚠️ Chưa tìm thấy file nhật ký $LOG_FILE"
        fi
        ;;

    list)
        echo "================================================================================"
        echo "        📋 DANH SÁCH CÁC CHIẾN THUẬT CÓ SẴN TRONG HỆ THỐNG"
        echo "================================================================================"
        "$PYTHON_BIN" -c "from execution.registry import list_available_strategies; strats = list_available_strategies(); [print(f'  • {s}') for s in strats]"
        echo "================================================================================"
        echo "  Khởi động bất kỳ chiến thuật nào bằng: ./quant_bot.sh start <tên_chiến_thuật>"
        ;;

    reset-killswitch)
        echo "🔄 Đang đặt lại trạng thái Kill Switch..."
        "$PYTHON_BIN" -c "from execution.risk_manager import RiskManager; rm = RiskManager(); rm.reset_kill_switch()"
        echo "✅ Kill Switch đã được mở khóa."
        ;;

    restart)
        "$0" stop
        sleep 1
        "$0" start "$STRATEGY"
        ;;

    *)
        echo "Hướng dẫn sử dụng:"
        echo "  ./quant_bot.sh start [tên_chiến_thuật]   # Khởi động bot chạy ngầm 24/7"
        echo "  ./quant_bot.sh status                   # Kiểm tra trạng thái và log"
        echo "  ./quant_bot.sh logs [tên_chiến_thuật]    # Xem nhật ký trực tiếp"
        echo "  ./quant_bot.sh stop                     # Dừng bot"
        echo "  ./quant_bot.sh restart [tên_chiến_thuật] # Khởi động lại"
        echo "  ./quant_bot.sh reset-killswitch         # Đặt lại bộ ngắt mạch khẩn cấp"
        echo "  ./quant_bot.sh list                     # Xem tất cả chiến thuật hỗ trợ"
        ;;
esac

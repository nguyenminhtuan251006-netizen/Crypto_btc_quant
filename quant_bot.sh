#!/bin/bash
# ==============================================================================
# BỘ ĐIỀU KHIỂN HỆ THỐNG TRADING BOT 24/7 (CRYPTO BTC QUANT LAB)
# ==============================================================================
# Hỗ trợ chạy song song độc lập nhiều bot trên Server Ubuntu Linux:
#   - Demo Mode:  Chạy trên sàn mô phỏng (Testnet / Mock trading)
#   - Live Mode:  Chạy trên sàn thật (Binance Real Futures)
#
# Cách sử dụng:
#   ./quant_bot.sh start chien_thuat_5 live    # Khởi động chiến thuật 5 trên tài khoản thật
#   ./quant_bot.sh start chien_thuat_4 demo    # Khởi động chiến thuật 4 trên tài khoản demo
#   ./quant_bot.sh status                      # Xem trạng thái tất cả các bot đang chạy
#   ./quant_bot.sh logs chien_thuat_5 live     # Xem nhật ký realtime chiến thuật 5
#   ./quant_bot.sh logs chien_thuat_4 demo     # Xem nhật ký realtime chiến thuật 4
#   ./quant_bot.sh stop chien_thuat_5 live     # Dừng chiến thuật 5
#   ./quant_bot.sh stop all                    # Dừng toàn bộ các bot
# ==============================================================================

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/home/tuannm/.venv/bin/python"
LOG_DIR="$WORKSPACE_DIR/logs"
mkdir -p "$LOG_DIR"

COMMAND="$1"
STRATEGY="${2:-chien_thuat_5}"
MODE="${3:-}"

# Portable launcher only for AFCX strategies; keep other strategies unchanged.
if [[ "$STRATEGY" = "chien_thuat_4" || "$STRATEGY" = "chien_thuat_5" || "$STRATEGY" = "strategy_4" || "$STRATEGY" = "strategy_5" ]]; then
    PYTHON_BIN="${QUANT_PYTHON:-$WORKSPACE_DIR/.venv/bin/python}"
    if [ ! -x "$PYTHON_BIN" ]; then
        if [ -x "/home/tuannm/.venv/bin/python" ]; then
            PYTHON_BIN="/home/tuannm/.venv/bin/python"
        else
            PYTHON_BIN="$(command -v python3)"
        fi
    fi
fi

# Tự động gán mode phù hợp nếu không truyền
if [ -z "$MODE" ]; then
    if [ "$STRATEGY" = "chien_thuat_5" ]; then
        MODE="live"
    elif [ "$STRATEGY" = "chien_thuat_4" ]; then
        MODE="demo"
    else
        MODE="demo"
    fi
fi

PID_FILE="$LOG_DIR/daemon_${STRATEGY}_${MODE}.pid"
LOG_FILE="$LOG_DIR/live_${STRATEGY}_${MODE}.log"

# Fallback cho file log cũ nếu đang dùng
if [ ! -f "$LOG_FILE" ] && [ -f "$LOG_DIR/live_${STRATEGY}.log" ]; then
    LOG_FILE="$LOG_DIR/live_${STRATEGY}.log"
fi

case "$COMMAND" in
    start)
        if [ -f "$PID_FILE" ]; then
            OLD_PID=$(cat "$PID_FILE")
            if ps -p "$OLD_PID" > /dev/null 2>&1; then
                echo "⚠️  Chiến thuật '$STRATEGY' (Chế độ: $MODE) đang chạy ngầm rồi!"
                echo "   • Tiến trình (PID): $OLD_PID"
                echo "   • Xem nhật ký:     ./quant_bot.sh logs $STRATEGY $MODE"
                echo "   • Dừng bot:        ./quant_bot.sh stop $STRATEGY $MODE"
                exit 0
            fi
        fi

        echo "================================================================================"
        echo "  🚀 KHỞI ĐỘNG HỆ THỐNG TRADING BOT CHẠY NGẦM 24/7 TRÊN SERVER"
        echo "================================================================================"
        echo "  • Chiến thuật nạp: $STRATEGY"
        echo "  • Môi trường sàn:  $(echo "$MODE" | tr '[:lower:]' '[:upper:]') ($( [ "$MODE" = "live" ] && echo "Sàn Binance Thật" || echo "Sàn Binance Demo" ))"
        echo "  • File nhật ký:    $LOG_FILE"
        echo "  • Máy chủ Linux:   Hoạt động độc lập 24/7 (Tắt app / tắt máy vẫn chạy)"
        echo "================================================================================"

        nohup env PYTHONUNBUFFERED=1 "$PYTHON_BIN" -u "$WORKSPACE_DIR/execution/daemon.py" --strategy "$STRATEGY" --mode "$MODE" > /dev/null 2>> "$LOG_FILE" &
        BOT_PID=$!
        echo "$BOT_PID" > "$PID_FILE"

        sleep 2
        if ps -p "$BOT_PID" > /dev/null 2>&1; then
            echo "✅ Bot '$STRATEGY' [$MODE] đã kích hoạt thành công! (PID: $BOT_PID)"
            echo "   • Xem nhật ký realtime: ./quant_bot.sh logs $STRATEGY $MODE"
            echo "   • Kiểm tra trạng thái:  ./quant_bot.sh status"
            echo "   • Dừng bot:             ./quant_bot.sh stop $STRATEGY $MODE"
        else
            echo "❌ Không thể khởi động bot. Chi tiết lỗi xem tại: $LOG_FILE"
            tail -n 15 "$LOG_FILE"
        fi
        ;;

    stop)
        if [ "$STRATEGY" = "all" ] || [ "$2" = "all" ]; then
            echo "🛑 Đang dừng toàn bộ các tiến trình bot..."
            PIDS=$(pgrep -f "execution/daemon.py")
            if [ -n "$PIDS" ]; then
                kill $PIDS
                sleep 1
                kill -9 $PIDS 2>/dev/null
                rm -f "$LOG_DIR"/*.pid
                echo "✅ Đã dừng toàn bộ bot thành công."
            else
                echo "ℹ️  Không có bot nào đang chạy."
            fi
            exit 0
        fi

        STOPPED=0
        if [ -f "$PID_FILE" ]; then
            BOT_PID=$(cat "$PID_FILE")
            if ps -p "$BOT_PID" > /dev/null 2>&1; then
                echo "🛑 Đang dừng bot '$STRATEGY' [$MODE] (PID: $BOT_PID)..."
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

        # Quét fallback theo tên chiến thuật
        PIDS=$(pgrep -f "execution/daemon.py --strategy $STRATEGY")
        if [ -n "$PIDS" ]; then
            echo "🛑 Đang dừng tiến trình liên quan: $PIDS"
            kill $PIDS
            rm -f "$PID_FILE"
            STOPPED=1
        fi

        if [ $STOPPED -eq 0 ]; then
            echo "ℹ️  Chiến thuật '$STRATEGY' [$MODE] hiện không chạy."
        fi
        ;;

    status)
        echo "================================================================================"
        echo "             📊 TRẠNG THÁI HỆ THỐNG TRADING BOT CHẠY NGẦM 24/7"
        echo "================================================================================"
        ACTIVE_PROCS=$(pgrep -a -f "execution/daemon.py" || true)

        if [ -n "$ACTIVE_PROCS" ]; then
            echo "  🟢 CÁC BOT ĐANG HOẠT ĐỘNG TRÊN SERVER:"
            echo "$ACTIVE_PROCS" | while read -r line; do
                PID=$(echo "$line" | awk '{print $1}')
                STRAT_ARG=$(echo "$line" | grep -o "\-\-strategy [^ ]*" | awk '{print $2}')
                MODE_ARG=$(echo "$line" | grep -o "\-\-mode [^ ]*" | awk '{print $2}')
                [ -z "$MODE_ARG" ] && MODE_ARG="demo"
                UPTIME=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ')
                MEM=$(ps -p "$PID" -o rss= 2>/dev/null | awk '{printf "%.1f MB", $1/1024}')
                echo "  ────────────────────────────────────────────────────────────────────────"
                echo "  • Tiến trình (PID):    $PID"
                echo "  • Chiến thuật:         ${STRAT_ARG:-unknown}"
                echo "  • Môi trường:          $(echo "$MODE_ARG" | tr '[:lower:]' '[:upper:]')"
                echo "  • Thời gian chạy:      $UPTIME"
                echo "  • Bộ nhớ tiêu thụ:     $MEM"
                if [[ "$STRAT_ARG" =~ ^(chien_thuat_4|chien_thuat_5|strategy_4|strategy_5)$ ]] && [ -f "$WORKSPACE_DIR/execution/afcx_daemon.py" ]; then
                    PROCESS_AGE=$(ps -p "$PID" -o etimes= 2>/dev/null | tr -d ' ')
                    SOURCE_MTIME=$(stat -c %Y "$WORKSPACE_DIR/execution/afcx_daemon.py" 2>/dev/null)
                    if [[ "$PROCESS_AGE" =~ ^[0-9]+$ && "$SOURCE_MTIME" =~ ^[0-9]+$ ]] &&
                       (( SOURCE_MTIME > $(date +%s) - PROCESS_AGE )); then
                        echo "  ⚠️ Mã bot ($STRAT_ARG) đã đổi sau khi tiến trình khởi động. Nạp mã mới: ./quant_bot.sh restart $STRAT_ARG $MODE_ARG"
                    fi
                fi
            done
        else
            echo "  ⚪ Hiện không có bot nào đang chạy."
            echo "  • Khởi động bot thật:  ./quant_bot.sh start chien_thuat_5 live"
            echo "  • Khởi động bot demo:  ./quant_bot.sh start chien_thuat_4 demo"
        fi
        echo "================================================================================"
        ;;

    logs)
        LOG_TARGET="$LOG_FILE"
        if [ ! -f "$LOG_TARGET" ]; then
            # Thử tìm file log không có hậu tố _mode
            if [ -f "$LOG_DIR/live_${STRATEGY}.log" ]; then
                LOG_TARGET="$LOG_DIR/live_${STRATEGY}.log"
            fi
        fi

        if [ -f "$LOG_TARGET" ]; then
            echo "👀 Đang theo dõi nhật ký realtime: $LOG_TARGET (Bấm Ctrl+C để thoát)..."
            tail -f "$LOG_TARGET"
        else
            echo "⚠️ Chưa tìm thấy file nhật ký: $LOG_TARGET"
        fi
        ;;

    list)
        echo "================================================================================"
        echo "        📋 DANH SÁCH CÁC CHIẾN THUẬT CÓ SẴN TRONG HỆ THỐNG"
        echo "================================================================================"
        "$PYTHON_BIN" -c "from execution.registry import list_available_strategies; strats = list_available_strategies(); [print(f'  • {s}') for s in strats]"
        echo "================================================================================"
        ;;

    reset-killswitch)
        KILL_STATE_FILE="$LOG_DIR/kill_switch_${STRATEGY}_${MODE}.json"
        echo "🔄 Đang đặt lại trạng thái Kill Switch cho '$STRATEGY' [$MODE]..."
        echo "   • File trạng thái: $KILL_STATE_FILE"
        "$PYTHON_BIN" -c "
from execution.risk_manager import RiskManager
import os
files = ['$KILL_STATE_FILE', '$LOG_DIR/kill_switch_state.json']
for sf in files:
    try:
        rm = RiskManager(state_file=sf)
        rm.reset_kill_switch()
        print(f'   ✅ Đã mở khóa: {sf}')
    except Exception as e:
        print(f'   ⚠️ {sf}: {e}')
"
        echo "✅ Hoàn tất đặt lại Kill Switch. Sẵn sàng giao dịch tiếp."
        ;;

    watchdog)
        # Watchdog: Giám sát tiến trình bot và tự động hồi sinh trong vòng 1 phút nếu bị sự cố
        ACTION="${4:-$2}"
        if [ "$2" = "install" ] || [ "$2" = "uninstall" ] || [ "$2" = "cron" ]; then
            ACTION="$2"
            STRATEGY="chien_thuat_5"
            MODE="live"
        fi

        CRON_CMD="* * * * * cd $WORKSPACE_DIR && ./quant_bot.sh watchdog $STRATEGY $MODE cron >> $LOG_DIR/watchdog.log 2>&1"
        case "$ACTION" in
            install)
                echo "🛡️ Đang cài đặt Watchdog (cron job mỗi phút) cho $STRATEGY [$MODE]..."
                (crontab -l 2>/dev/null | grep -v "quant_bot.sh watchdog"; echo "$CRON_CMD") | crontab -
                echo "✅ Watchdog đã cài đặt thành công! Bot sẽ tự khởi động lại sau tối đa 1 phút nếu crash."
                ;;
            uninstall)
                echo "🛑 Đang gỡ bỏ Watchdog cron job..."
                crontab -l 2>/dev/null | grep -v "quant_bot.sh watchdog" | crontab -
                echo "✅ Đã gỡ bỏ Watchdog."
                ;;
            cron)
                if [ -f "$PID_FILE" ]; then
                    BOT_PID=$(cat "$PID_FILE")
                    if ! ps -p "$BOT_PID" > /dev/null 2>&1; then
                        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚨 Watchdog: Bot $STRATEGY [$MODE] (PID $BOT_PID) đã dừng đột ngột! Đang tự khởi động lại..."
                        "$0" start "$STRATEGY" "$MODE"
                    fi
                fi
                ;;
            *)
                echo "Sử dụng Watchdog:"
                echo "  ./quant_bot.sh watchdog [chiến_thuật] [live|demo] install   # Tự động hồi sinh khi crash"
                echo "  ./quant_bot.sh watchdog [chiến_thuật] [live|demo] uninstall # Tắt tính năng tự hồi sinh"
                ;;
        esac
        ;;

    restart)
        "$0" stop "$STRATEGY" "$MODE"
        sleep 1
        "$0" start "$STRATEGY" "$MODE"
        ;;

    *)
        echo "Cách sử dụng:"
        echo "  ./quant_bot.sh start [chiến_thuật] [live|demo]    # Khởi động bot chạy ngầm 24/7"
        echo "  ./quant_bot.sh status                             # Xem tất cả bot đang chạy"
        echo "  ./quant_bot.sh logs [chiến_thuật] [live|demo]     # Xem nhật ký trực tiếp"
        echo "  ./quant_bot.sh stop [chiến_thuật] [live|demo]     # Dừng một bot"
        echo "  ./quant_bot.sh stop all                           # Dừng toàn bộ bot"
        echo "  ./quant_bot.sh restart [chiến_thuật] [live|demo]  # Khởi động lại bot"
        echo "  ./quant_bot.sh reset-killswitch [chiến_thuật] [mode] # Mở khóa Kill Switch"
        echo "  ./quant_bot.sh watchdog [chiến_thuật] [mode] install # Tự động hồi sinh bot 24/7"
        echo "  ./quant_bot.sh list                               # Xem danh sách chiến thuật"
        ;;
esac

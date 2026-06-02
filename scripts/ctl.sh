#!/usr/bin/env bash
set -euo pipefail

APP_NAME="larkBot"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT_DIR/run"
PID_FILE="$PID_DIR/bot.pid"
LOG_FILE="$ROOT_DIR/logs/bot.log"

mkdir -p "$PID_DIR" "$ROOT_DIR/logs"

_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    fi
}

_is_running() {
    local pid
    pid=$(_pid)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

cmd_start() {
    if _is_running; then
        echo "$APP_NAME is already running (PID $(_pid))"
        exit 1
    fi

    # Kill any orphaned consumers before starting
    pkill -f "lark-cli event consume im.message.receive_v1" 2>/dev/null || true
    sleep 0.5

    echo "Starting $APP_NAME..."
    cd "$ROOT_DIR"
    nohup python3 -m bot >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
        echo "$APP_NAME started (PID $pid)"
        echo "Logs: $LOG_FILE"
    else
        echo "Failed to start $APP_NAME — check $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

cmd_stop() {
    if ! _is_running; then
        echo "$APP_NAME is not running"
        rm -f "$PID_FILE"
        # Kill any orphaned lark-cli event consumers
        pkill -f "lark-cli event consume im.message.receive_v1" 2>/dev/null || true
        return
    fi

    local pid
    pid=$(_pid)
    echo "Stopping $APP_NAME (PID $pid)..."

    # Kill the entire process group (parent + child lark-cli)
    kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true

    local i=0
    while [ $i -lt 10 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "$APP_NAME stopped"
            rm -f "$PID_FILE"
            # Cleanup any remaining lark-cli consumers
            pkill -f "lark-cli event consume im.message.receive_v1" 2>/dev/null || true
            return
        fi
        sleep 1
        i=$((i + 1))
    done

    echo "Force killing $APP_NAME..."
    kill -9 "$pid" 2>/dev/null || true
    pkill -9 -f "lark-cli event consume im.message.receive_v1" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "$APP_NAME killed"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    if _is_running; then
        local pid
        pid=$(_pid)
        local elapsed
        elapsed=$(ps -p "$pid" -o etime= 2>/dev/null | xargs)
        echo "$APP_NAME is running"
        echo "  PID:    $pid"
        echo "  Uptime: $elapsed"
        echo "  Log:    $LOG_FILE"
    else
        echo "$APP_NAME is not running"
        [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
    fi
}

cmd_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "No log file yet: $LOG_FILE"
        exit 1
    fi
    tail -f "$LOG_FILE"
}

case "${1:-help}" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    status)  cmd_status  ;;
    logs)    cmd_logs    ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac

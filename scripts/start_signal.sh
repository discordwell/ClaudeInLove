#!/bin/bash
# Launch Signal Desktop with remote debugging enabled

SIGNAL_PORT=${SIGNAL_DEBUG_PORT:-9222}

echo "Starting Signal Desktop with remote debugging on port $SIGNAL_PORT..."

# Try common Signal Desktop locations
if command -v signal-desktop &> /dev/null; then
    signal-desktop --remote-debugging-port=$SIGNAL_PORT &
elif [ -f "/usr/bin/signal-desktop" ]; then
    /usr/bin/signal-desktop --remote-debugging-port=$SIGNAL_PORT &
elif [ -f "/opt/Signal/signal-desktop" ]; then
    /opt/Signal/signal-desktop --remote-debugging-port=$SIGNAL_PORT &
elif [ -f "/snap/bin/signal-desktop" ]; then
    /snap/bin/signal-desktop --remote-debugging-port=$SIGNAL_PORT &
else
    # Windows (via WSL)
    if [ -f "/mnt/c/Users/$USER/AppData/Local/Programs/signal-desktop/Signal.exe" ]; then
        "/mnt/c/Users/$USER/AppData/Local/Programs/signal-desktop/Signal.exe" --remote-debugging-port=$SIGNAL_PORT &
    else
        echo "Signal Desktop not found. Please install it or update this script."
        exit 1
    fi
fi

echo "Signal Desktop started. Wait for it to fully load before running ClaudeInLove."
echo "Debug URL: http://localhost:$SIGNAL_PORT"

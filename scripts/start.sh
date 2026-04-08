#!/bin/bash
set -e

# Check if apfel is installed
if ! command -v apfel &> /dev/null; then
    echo "Error: apfel not found. Install with: brew install Arthur-Ficial/tap/apfel"
    exit 1
fi

# Check if already running
if curl -s http://localhost:11434/health > /dev/null 2>&1; then
    echo "apfel already running on localhost:11434"
    exit 0
fi

# Start apfel server (nohup keeps it running after terminal closes)
echo "Starting apfel server..."
nohup apfel --serve > /dev/null 2>&1 &
APFEL_PID=$!

# Wait for server to be ready
for i in {1..10}; do
    if curl -s http://localhost:11434/health > /dev/null 2>&1; then
        echo "apfel running on localhost:11434 (PID: $APFEL_PID)"
        exit 0
    fi
    sleep 1
done

echo "Error: apfel failed to start within 10 seconds"
exit 1

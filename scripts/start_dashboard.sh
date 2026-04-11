#!/bin/bash
# start_dashboard.sh — start the AgentScope local dashboard on port 7844
set -e

DASHBOARD_DIR="$(cd "$(dirname "$0")/.." && pwd)/dashboard"

if [ ! -d "$DASHBOARD_DIR/node_modules" ]; then
    echo "Installing dashboard dependencies..."
    cd "$DASHBOARD_DIR"
    npm install -q
fi

echo "Starting AgentScope Dashboard on http://localhost:7844"
echo "Collector expected at http://localhost:7843 (start with scripts/start_collector.py)"
echo ""

cd "$DASHBOARD_DIR"
npm run dev

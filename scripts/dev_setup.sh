#!/bin/bash
# dev_setup.sh — one-command development environment setup
set -e

echo "=== AgentScope Dev Setup ==="

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
major=$(echo "$python_version" | cut -d. -f1)
minor=$(echo "$python_version" | cut -d. -f2)

if [ "$major" -lt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -lt 11 ]); then
    echo "ERROR: Python 3.11+ required (found $python_version)"
    exit 1
fi

echo "Python $python_version ✓"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install package with dev extras — use .venv/bin/pip explicitly to avoid
# accidentally installing into a Homebrew or system Python
echo "Installing agentscope[dev]..."
.venv/bin/pip install -e ".[dev]" -q

# Copy .env if missing
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ".env created from .env.example"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate the environment:  source .venv/bin/activate"
echo "Run tests:                 .venv/bin/pytest   (use this, not bare 'pytest')"
echo "Start collector:           .venv/bin/python scripts/start_collector.py"
echo "Health check:              curl http://localhost:7843/health"

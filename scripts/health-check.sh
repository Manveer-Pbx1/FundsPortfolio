#!/bin/bash
# Health check script for CI/CD pipeline

echo "Running health check..."

# Start the app in background
python -m gunicorn --bind 0.0.0.0:5000 --workers 1 --timeout 30 funds_portfolio.app:app &
APP_PID=$!

# Wait for app to start
sleep 5

# Check health endpoint
if curl -f http://localhost:5000/health > /dev/null 2>&1; then
    echo "✅ Health check passed"
    kill $APP_PID
    exit 0
else
    echo "❌ Health check failed"
    kill $APP_PID
    exit 1
fi
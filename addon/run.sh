#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "Starting Air Quality UI..."

cd /app
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8099 --no-access-log

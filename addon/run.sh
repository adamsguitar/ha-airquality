#!/usr/bin/with-contenv bashio
set -e

bashio::log.info "Starting Air Quality UI..."

cd /app
exec python3 -c "import logging; import uvicorn; logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'); uvicorn.run('main:app', host='0.0.0.0', port=8099, access_log=False, log_config=None)"

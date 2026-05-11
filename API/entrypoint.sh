#!/bin/bash
set -e

# Apply pending migrations
echo "Running database migrations..."
alembic upgrade head

# Run seeds (idempotent, safe to run every time)
echo "Running database seeds..."
python -m src.seeds.run

# Execute the main command (CMD from Dockerfile or docker-compose)
exec "$@"

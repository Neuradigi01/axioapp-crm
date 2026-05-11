#!/bin/bash

# A script to manage the API application stack using production docker-compose files.
# Usage:
#   ./docker-helper.sh up              - Start API stack (prod mode)
#   ./docker-helper.sh down            - Stop and remove the stack
#   ./docker-helper.sh up-celery       - Start API stack with Celery (prod mode)
#   ./docker-helper.sh encrypt-secrets - Encrypt sensitive values in .env
#   ./docker-helper.sh decrypt-secrets - Decrypt sensitive values in .env

set -e

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"

if [ -z "$1" ]; then
    echo "Error: No command provided."
    echo "Usage: $0 {up|down|up-celery|encrypt-secrets|decrypt-secrets}"
    exit 1
fi

case "$1" in
    up)
        echo "Starting the API stack in production mode..."
        chmod -R 777 logs/ 2>/dev/null || true
        docker compose $COMPOSE_FILES up --build -d
        echo "API stack started successfully."
        ;;
    down)
        echo "Stopping and removing the API stack..."
        docker compose $COMPOSE_FILES down -v
        echo "API stack stopped successfully."
        ;;
    up-celery)
        echo "Starting the API stack with Celery in production mode..."
        chmod -R 777 logs/ 2>/dev/null || true
        chmod -R 777 flower/ 2>/dev/null || true
        docker compose $COMPOSE_FILES --profile celery up --build -d
        echo "API stack with Celery started successfully."
        ;;
    encrypt-secrets)
        echo "Encrypting sensitive values in .env..."
        docker compose $COMPOSE_FILES run --rm --no-deps --entrypoint "python manage_secrets.py encrypt" api
        ;;
    decrypt-secrets)
        echo "Decrypting sensitive values in .env..."
        docker compose $COMPOSE_FILES run --rm --no-deps --entrypoint "python manage_secrets.py decrypt" api
        ;;
    *)
        echo "Error: Invalid command '$1'."
        echo "Usage: $0 {up|down|up-celery|encrypt-secrets|decrypt-secrets}"
        exit 1
        ;;
esac

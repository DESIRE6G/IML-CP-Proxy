#!/bin/bash

SOURCE_CONFIG="example/proxy_config.json"
DEST_CONFIG="proxy_config.json"

if [ -f "$DEST_CONFIG" ]; then
    if cmp -s "$DEST_CONFIG" "$SOURCE_CONFIG"; then
        echo "$DEST_CONFIG is already identical to example. Skipping copy."
    else
        BACKUP_NAME="${DEST_CONFIG}.bak_$(date +%Y%m%d_%H%M%S)"
        echo "--- WARNING ---"
        echo "Found modified $DEST_CONFIG in root!"
        echo "Backing it up to: $BACKUP_NAME"
        mv "$DEST_CONFIG" "$BACKUP_NAME"

        echo "Copying example proxy_config..."
        cp "$SOURCE_CONFIG" ./
    fi
else
    echo "Copying example proxy_config..."
    cp "$SOURCE_CONFIG" ./
fi

echo "Copying example proxy_config and example build"
cp example/proxy_config.json ./
cp -r example/p4_build ./build

echo "Down compose if running..."
docker compose down --volumes --remove-orphans

if [[ "$1" == "--clean" ]]; then
    echo "Forcing clean build (no cache)..."
    docker compose -f docker-compose.yml -f docker-compose.demo.yml build --no-cache
fi

echo "Starting IML-CP-Proxy Demo Environment..."
docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build
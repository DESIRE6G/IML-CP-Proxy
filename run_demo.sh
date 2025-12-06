#!/bin/bash

echo "Down compose if running..."
docker compose down --volumes --remove-orphans

echo "Starting IML-CP-Proxy Demo Environment..."
docker compose -f docker-compose.yml -f docker-compose.demo.yml up --build

#!/bin/zsh

cd "$(dirname "$0")"
docker-compose up --build -d

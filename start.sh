#!/bin/bash
set -e

echo "== Stop Ollama yang berjalan di host =="
systemctl stop ollama 2>/dev/null || pkill -f "ollama serve" 2>/dev/null || true
sleep 2

echo "== Force stop & hapus semua container lama =="
for name in claims_db-medallion claims_ollama claims_streamlit; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
        echo "  Removing: $name"
        docker stop "$name" 2>/dev/null || true
        # Use -v to also remove anonymous volumes (resets Oracle DB data)
        docker rm -fv "$name" 2>/dev/null || true
    fi
done

echo "== Bersihkan sisa compose + dangling volumes =="
docker compose down --remove-orphans --volumes 2>/dev/null || true

echo "== Build & jalankan semua container =="
docker compose up -d --build

echo "== Hapus dangling images (<none>) =="
docker image prune -f

echo ""
echo "== Status container =="
docker compose ps

echo ""
echo "== Docker images aktif =="
docker images

#!/bin/bash

set -e

OLLAMA_MODELS=("llava:7b" "qwen2:7b")

# ── 1. Install Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[INFO] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker && systemctl start docker
    usermod -aG docker "$USER" 2>/dev/null || true
else
    echo "[OK] Docker already installed."
fi

# ── 1c. Install NVIDIA Container Toolkit (GPU pass-through for Docker) ────────
if command -v nvidia-smi &>/dev/null; then
    if ! dpkg -l | grep -q nvidia-container-toolkit 2>/dev/null; then
        echo "[INFO] Installing NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        sudo apt-get update -qq
        sudo apt-get install -y nvidia-container-toolkit
        sudo nvidia-ctk runtime configure --runtime=docker
        sudo systemctl restart docker
        echo "[OK] NVIDIA Container Toolkit installed & Docker restarted."
    else
        echo "[OK] NVIDIA Container Toolkit already installed."
        # Ensure nvidia runtime is configured in Docker
        if ! docker info 2>/dev/null | grep -q "nvidia"; then
            echo "[INFO] Configuring NVIDIA runtime for Docker..."
            sudo nvidia-ctk runtime configure --runtime=docker
            sudo systemctl restart docker
        fi
    fi
else
    echo "[WARN] nvidia-smi not found — GPU will NOT be used. Ollama will run on CPU."
fi

# ── 1b. Install Docker Compose plugin ─────────────────────────────────────────
if ! docker compose version &>/dev/null; then
    echo "[INFO] Installing Docker Compose plugin..."
    DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
    mkdir -p "$DOCKER_CONFIG/cli-plugins"
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
        -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
    chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
    echo "[OK] Docker Compose plugin installed."
else
    echo "[OK] Docker Compose already installed."
fi

# ── 2. Install Ollama ─────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo "[INFO] Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
else
    echo "[OK] Ollama already installed."
fi

# ── 3. Pull Ollama models (skip if already pulled) ───────────────────────────
ollama serve &>/dev/null & OLLAMA_PID=$!
sleep 5
for model in "${OLLAMA_MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "^${model}"; then
        echo "[OK] Model already pulled: $model"
    else
        echo "[INFO] Pulling: $model ..."
        ollama pull "$model"
    fi
done
kill "$OLLAMA_PID" 2>/dev/null || true

# ── 4. Validate .env ──────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[ERROR] .env not found! Create it manually first." && exit 1
fi
echo "[OK] .env found."

# ── 6. Stop host Ollama  ──────────────────────────────────
sudo systemctl stop ollama 2>/dev/null || pkill -f "ollama serve" 2>/dev/null || true
sleep 2

# ── 7. Stop & remove previous containers ─────────────────────────────────────────
for name in claims_db-medallion claims_ollama claims_streamlit; do
    docker stop "$name" 2>/dev/null || true
    docker rm -fv "$name" 2>/dev/null || true
done
docker compose down --remove-orphans --volumes 2>/dev/null || true

# ── 8. Build & start ──────────────────────────────────────────────────────────
docker compose up -d --build
docker image prune -f 2>/dev/null || true

# ── 9. Register systemd service agar otomatis start saat VM reboot ───────────
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="/etc/systemd/system/insuranceclaim.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=InsuranceClaim Docker Compose
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$WORKDIR
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose stop
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable insuranceclaim.service
echo "[OK] systemd service 'insuranceclaim' aktif — akan auto-start saat VM reboot."

# ── 10. Status ─────────────────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo "  Streamlit : http://$IP:8501"
echo "  Ollama    : http://$IP:11434"
echo "  Oracle DB : $IP:1521 (FREEPDB1)"
echo "========================================"

# Show GPU status
if command -v nvidia-smi &>/dev/null; then
    echo ""
    echo "[GPU STATUS]"
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    echo ""
    echo "[GPU in Ollama container]"
    docker exec claims_ollama nvidia-smi --query-gpu=name,utilization.gpu --format=csv,noheader 2>/dev/null \
        || echo "  (container not ready yet, check again in 30s)"
fi

echo ""
docker compose ps
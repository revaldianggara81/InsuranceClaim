#!/bin/bash
# Tunggu Ollama server siap, lalu pull model yang belum ada

echo "Menunggu Ollama server..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "Ollama server siap."

echo "Model yang tersedia:"
ollama list

# Pull llava:7b jika belum ada
if ! ollama list | grep -q "llava:7b"; then
    echo "Pulling llava:7b (VLM model)..."
    ollama pull llava:7b
else
    echo "llava:7b sudah tersedia."
fi

# Pull qwen2:7b jika belum ada
if ! ollama list | grep -q "qwen2:7b"; then
    echo "Pulling qwen2:7b (text model)..."
    ollama pull qwen2:7b
else
    echo "qwen2:7b sudah tersedia."
fi

echo ""
echo "== Model aktif =="
ollama list

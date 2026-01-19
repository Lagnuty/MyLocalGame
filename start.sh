#!/bin/bash

# Dodger Battle Royale - Server Launcher
# Works on Mac and Linux

echo "================================"
echo "🎮 Dodger Battle Royale"
echo "================================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден. Пожалуйста установите Python 3"
    exit 1
fi

# Install requirements
echo "📦 Установка зависимостей..."
pip install -r requirements.txt --quiet

if [ $? -ne 0 ]; then
    echo "❌ Ошибка при установке зависимостей"
    exit 1
fi

# Get local IP
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
else
    # Linux
    LOCAL_IP=$(hostname -I | awk '{print $1}')
fi

echo "✅ Зависимости установлены"
echo ""
echo "================================"
echo "🌍 Адрес для подключения:"
echo "http://$LOCAL_IP:5000"
echo "================================"
echo ""
echo "Игроки должны открыть эту ссылку в браузере"
echo "Ctrl+C для остановки сервера"
echo ""

# Run the server
python3 server.py

@echo off
REM Dodger Battle Royale - Server Launcher for Windows

echo ================================
echo Dodger Battle Royale
echo ================================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python не найден. Пожалуйста установите Python 3
    echo Скачайте с https://www.python.org/
    pause
    exit /b 1
)

REM Install requirements
echo.
echo Установка зависимостей...
pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo ERROR: Ошибка при установке зависимостей
    pause
    exit /b 1
)

REM Get local IP
echo.
echo ================================
echo.
for /f "tokens=2 delims=: " %%a in ('ipconfig ^| find "IPv4"') do (
    set "LOCAL_IP=%%a"
    goto :found_ip
)

:found_ip
echo.
echo Адрес для подключения:
echo http://%LOCAL_IP%:5000
echo.
echo ================================
echo.
echo Игроки должны открыть эту ссылку в браузере
echo Нажми Ctrl+C для остановки сервера
echo.

REM Run the server
python server.py
pause

#!/bin/bash

set -e # Остановка скрипта при любой критической ошибке

echo "================================================="
echo "       🚀 Установка KAPAT (Klipper Auto PA Tuning)"
echo "================================================="

# Пути
KAPAT_DIR="$HOME/KAPAT"
KLIPPER_EXTRAS="$HOME/klipper/klippy/extras"
SERVICE_FILE="/etc/systemd/system/kapat.service"

# 1. Установка системных зависимостей (важно для чистых образов!)
echo "📦 Проверка системных пакетов (python3-venv)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip

# 2. Загрузка или обновление репозитория
if [ -d "$KAPAT_DIR" ]; then
    echo "🔄 Обновление репозитория KAPAT..."
    cd "$KAPAT_DIR"
    git pull
else
    echo "📥 Скачивание KAPAT с GitHub..."
    git clone https://github.com/vzagranichnyy/KAPAT.git "$KAPAT_DIR"
fi

# 3. Настройка виртуального окружения Python
echo "🐍 Настройка изолированного окружения Python..."
cd "$KAPAT_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. Установка библиотек
echo "📦 Установка необходимых библиотек (FastAPI, NumPy, SciPy...)..."
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

# 5. Определение модуля запуска (ИСПРАВЛЕНО ДЛЯ РАБОТЫ СЕРВЕРА)
if [ -f "$KAPAT_DIR/prusa_pa_tuner/app.py" ]; then
    UVICORN_APP="prusa_pa_tuner.app:app"
else
    UVICORN_APP="app:app"
fi

# 6. Создание папки для логов
echo "📁 Создание папки для сохранения результатов тестов (runs)..."
mkdir -p "$KAPAT_DIR/runs"
mkdir -p "$KAPAT_DIR/prusa_pa_tuner/runs"

# 7. Копирование модулей Klipper и перезапуск
echo "⚙️ Установка файлов для Klipper..."
if [ -d "$KLIPPER_EXTRAS" ]; then
    # Ищем, где именно лежат ваши файлы klipper в репозитории
    if [ -d "$KAPAT_DIR/klipper/klippy/extras" ]; then
        cp $KAPAT_DIR/klipper/klippy/extras/*.py $KLIPPER_EXTRAS/
    elif [ -d "$KAPAT_DIR/klipper_extras" ]; then
        cp $KAPAT_DIR/klipper_extras/*.py $KLIPPER_EXTRAS/
    fi
    echo "✅ Модули Klipper скопированы."
    
    echo "🔄 Перезапуск Klipper для применения изменений..."
    sudo systemctl restart klipper || true
else
    echo "⚠️ Папка $KLIPPER_EXTRAS не найдена! Klipper установлен по другому пути?"
fi

# 8. Автоматическое копирование макроса kapat.cfg (НОВОЕ!)
echo "📄 Настройка конфигурации Klipper..."
if [ -f "$KAPAT_DIR/kapat.cfg" ]; then
    if [ -d "$HOME/printer_data/config" ]; then
        cp "$KAPAT_DIR/kapat.cfg" "$HOME/printer_data/config/"
        echo "✅ Файл kapat.cfg скопирован в ~/printer_data/config/"
    elif [ -d "$HOME/klipper_config" ]; then
        cp "$KAPAT_DIR/kapat.cfg" "$HOME/klipper_config/"
        echo "✅ Файл kapat.cfg скопирован в ~/klipper_config/"
    else
        echo "⚠️ Папка с конфигами не найдена. Скопируйте kapat.cfg вручную."
    fi
else
    echo "⚠️ Файл kapat.cfg не найден в репозитории! Не забудьте его создать."
fi

# 9. Настройка автозапуска (systemd)
echo "🔌 Настройка службы автозапуска сервера..."
cat <<EOF | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=KAPAT Web Server
After=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$KAPAT_DIR
ExecStart=$KAPAT_DIR/venv/bin/uvicorn $UVICORN_APP --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable kapat
sudo systemctl restart kapat

echo "================================================="
echo "🎉 Установка KAPAT успешно завершена!"
echo ""
echo "❗ ВАЖНО: Добавьте строку [include kapat.cfg] в ваш printer.cfg!"
echo ""
echo "🌐 Веб-интерфейс доступен по адресу:"
echo "   http://<IP-адрес-вашего-принтера>:8000"
echo "================================================="
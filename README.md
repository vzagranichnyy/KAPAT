# KAPAT - Klipper Auto Pressure Advance Tuning

**KAPAT** is a loadcell-based automatic Pressure Advance calibration tool for Klipper, based on the original [PrusaPATuner by CNCKitchen](https://github.com/CNCKitchen/PrusaPATuner).

Unlike traditional visual calibration, this tool directly measures the pressure inside the nozzle using a loadcell (Strain Gauge) to calculate the optimal Pressure Advance value.

This fork features a **completely redesigned, modern, two-column UI**, optimized specifically for Klipper, with built-in filament preset management and an intuitive workflow.

<p align="center">
  <img src="screenshot.png" width="32%" />
  <img src="screenshot1.png" width="32%" />
  <img src="screenshot2.png" width="32%" />
</p>

## Features
* **Klipper Native:** Fully adapted for Moonraker/Klipper API.
* **Modern UI:** Sleek dark theme with dual-column layout and intuitive sliders.
* **Preset Management:** Save and load your filament settings directly from the web interface.
* **Real-time Analytics:** Smooth live loadcell graph and per-segment step-response analysis.
* **Easy Cleanup:** Delete old `.npz` run files right from the dashboard.
* **Replay Engine:** Re-analyze previously recorded telemetry logs without heating up the printer.

## Installation & Usage
1. Clone this repository to your Klipper host (e.g., Raspberry Pi).
2. Copy the Python script from the `klipper_extras` folder into your `~/klipper/klippy/extras/` directory.
3. Include the provided `kapat.cfg` macro in your Klipper `printer.cfg`.
4. Install the required Python dependencies:
   ```bash
pip install -r requirements.txt

Run the FastAPI server:

uvicorn app:app --host 0.0.0.0 --port 8000

6. Open `http://<your-pi-ip>:8000` in your browser to access the dashboard.

## Credits
* **Original Concept & Math:** [Stefan (CNCKitchen)](https://github.com/CNCKitchen).
* **Klipper integration & UI redesign:** Vitaliy Zagranichnyy.

---

# KAPAT - Автоматическая калибровка Pressure Advance для Klipper

**KAPAT** — это инструмент автоматической калибровки Pressure Advance для Klipper с использованием тензодатчика (loadcell), основанный на оригинальном проекте [PrusaPATuner от CNCKitchen](https://github.com/CNCKitchen/PrusaPATuner).

В отличие от традиционной визуальной калибровки (печати линий или башен), этот инструмент напрямую измеряет давление внутри сопла с помощью тензодатчика для вычисления оптимального значения Pressure Advance.

Этот форк (версия) включает в себя **полностью переработанный, современный интерфейс в две колонки**, специально оптимизированный для Klipper, со встроенным управлением пресетами для пластика и интуитивно понятным рабочим процессом.

## Особенности
* **Нативная работа с Klipper:** Полная адаптация под API Moonraker/Klipper.
* **Современный интерфейс:** Стильная темная тема с двухколоночной компоновкой и удобными ползунками.
* **Управление пресетами:** Сохраняйте и загружайте настройки для разных типов пластика прямо из веб-интерфейса.
* **Аналитика в реальном времени:** Плавный график показаний тензодатчика в реальном времени и детальный анализ каждого сегмента теста.
* **Легкая очистка:** Удаляйте старые файлы тестов `.npz` прямо с панели управления одним кликом.
* **Движок повторов (Replay):** Проводите повторный анализ ранее записанных логов телеметрии без необходимости снова нагревать принтер и тратить пластик.

## Установка и использование
1. Склонируйте этот репозиторий на ваш хост Klipper (например, на Raspberry Pi).
2. Скопируйте Python-скрипт из папки `klipper_extras` в вашу директорию `~/klipper/klippy/extras/`.
3. Подключите файл с макросом `kapat.cfg` в ваш основной конфигурационный файл Klipper `printer.cfg` (через команду include).
4. Установите необходимые зависимости Python:
   ```bash
pip install -r requirements.txt

Запустите сервер FastAPI:

uvicorn app:app --host 0.0.0.0 --port 8000

6. Откройте `http://<your-pi-ip>:8000` в браузере для доступа к панели управления.

## Авторы
* **Оригинальная концепция и математика:** [Stefan (CNCKitchen)](https://github.com/CNCKitchen).
* **Интеграция с Klipper и новый интерфейс:** Vitaliy Zagranichnyy.

## License
This project is open-source and builds upon the original work by CNCKitchen. Please refer to the `LICENSE` file in this repository for specific terms and conditions.




#!/bin/sh

# Запуск uvicorn
gunicorn app.main:app -c gunicorn_conf.py &

# Ожидание завершения всех процессов
wait

@echo off
chcp 65001 >nul
cd /d "%~dp0"
set OLLAMA_MODELS=D:\md
set OLLAMA_CUDA_VISIBLE_DEVICES=-1
set OLLAMA_NUM_PARALLEL=1
taskkill /f /im ollama.exe 2>nul
start "" "C:\Users\timak\AppData\Local\Programs\Ollama\ollama.exe" serve
timeout /t 4 /nobreak >nul
"C:\Users\timak\AppData\Local\Python\pythoncore-3.12-64\python.exe" main.py

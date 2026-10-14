@echo off
title RAiF Local GPU Daemon (127.0.0.1:11434)
cd /d "%~dp0.."
echo ======================================================================
echo 🚀 Rassvet AI Fabric - Local GPU Inference Daemon
echo    Host: http://127.0.0.1:11434/chat
echo    GPU:  NVIDIA GeForce RTX 5070 Ti (16 GB VRAM)
echo ======================================================================
python scripts\local-gpu-daemon.py --host 127.0.0.1 --port 11434
pause

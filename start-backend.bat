@echo off
title Velo.gg - API
cd /d "%~dp0server"
echo Starting API on http://127.0.0.1:5001
echo First prediction may take ~10 seconds while the model loads.
echo.
python app.py
pause

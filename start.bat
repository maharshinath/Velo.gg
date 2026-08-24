@echo off
title Velo
cd /d "%~dp0"
echo Launching backend and frontend in separate windows...
start "VCT API" cmd /k "%~dp0start-backend.bat"
timeout /t 2 /nobreak >nul
start "VCT App" cmd /k "%~dp0start-frontend.bat"
timeout /t 3 /nobreak >nul
start http://localhost:5173
echo.
echo App: http://localhost:5173
echo API: http://127.0.0.1:5001/api
echo Close both terminal windows to stop the servers.

@echo off
title Velo - App
cd /d "%~dp0client"
echo Starting app on http://localhost:5173
echo.
npm run dev
pause

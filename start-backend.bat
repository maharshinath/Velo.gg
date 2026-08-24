@echo off
title Velo - API
cd /d "%~dp0server"
echo Starting API on http://127.0.0.1:5001
echo First prediction may take ~10 seconds while the model loads.
echo.
python -c "from app import app; app.run(debug=True, port=5001, use_reloader=False)"
pause

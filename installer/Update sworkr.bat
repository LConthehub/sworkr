@echo off
rem Gets the newest sworkr and restarts it. Your records stay. Double-click this file.
cd /d "%~dp0"
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker isn't running yet. Open Docker Desktop, wait for "Engine running", then try again.
  pause
  exit /b 1
)
docker compose pull
docker compose up -d
echo.
echo Done. sworkr is up to date. Your records were kept, and a copy was saved before any upgrade.
pause

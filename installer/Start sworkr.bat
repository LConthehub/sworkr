@echo off
rem Starts sworkr and opens it in your browser. Double-click this file.
cd /d "%~dp0"
docker info >nul 2>&1
if errorlevel 1 (
  echo.
  echo Docker isn't running yet.
  echo Open Docker Desktop, wait until it says "Engine running", then double-click this file again.
  echo.
  pause
  exit /b 1
)
echo Starting sworkr. The first time it downloads it, which takes a few minutes...
docker compose up -d
if errorlevel 1 (
  echo.
  echo Something went wrong. The message above says what. sworkr.com/docs/troubleshooting.html can help.
  pause
  exit /b 1
)
ping -n 6 127.0.0.1 >nul
start "" http://localhost:8008

@echo off
rem Starts sworkr on Windows. Double-click this file. Needs Docker Desktop to be running.
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo Docker Desktop isn't running.
    echo Open Docker Desktop from the Start menu, wait until it says "Engine running", then double-click start.bat again.
    echo Don't have it yet? Get it from https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

echo Starting sworkr. The first time takes a few minutes while it downloads what it needs...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo sworkr couldn't start. The lines above say why.
    echo.
    pause
    exit /b 1
)

echo.
echo sworkr is running at http://localhost:8008
echo It keeps running in the background, and starts again by itself when Docker Desktop starts.
echo To stop it, double-click stop.bat.
echo.
start "" http://localhost:8008
pause

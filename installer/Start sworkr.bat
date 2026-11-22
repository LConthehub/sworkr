@echo off
rem Starts sworkr and opens it in your browser. Double-click this file.
rem If Docker Desktop is installed but closed, this opens it and waits for it.
rem "Update sworkr" runs this file with the word update, which gets the newest version first.
setlocal
cd /d "%~dp0"
title sworkr
set "DOCKER_APP=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
rem Right after installing Docker, Windows may not know where its command is until you sign out and in.
set "PATH=%PATH%;%ProgramFiles%\Docker\Docker\resources\bin"

docker info >nul 2>&1
if not errorlevel 1 goto docker_ready

where docker >nul 2>&1
if errorlevel 1 if not exist "%DOCKER_APP%" goto no_docker

if exist "%DOCKER_APP%" (
  echo Opening Docker Desktop. The first time, it may ask you something: answer it, then come back here.
  start "" "%DOCKER_APP%"
) else (
  echo Docker isn't running. Open Docker Desktop from the Start menu, and this window will carry on by itself.
)
echo Waiting for Docker to be ready. This can take a minute or two...
set /a tries=0
:wait_docker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a tries+=1
if %tries% lss 80 goto wait_docker
echo.
echo Docker still isn't ready after 4 minutes.
echo Look at Docker Desktop: when it says "Engine running", double-click this file again.
echo.
pause
exit /b 1

:no_docker
echo.
echo Docker Desktop isn't installed yet. It's the free program sworkr runs inside.
echo Your browser will open its download page. Install it, open it once, then double-click this file again.
echo.
start "" https://www.docker.com/products/docker-desktop/
pause
exit /b 1

:docker_ready
if /i "%~1"=="update" (
  echo Getting the newest sworkr...
  docker compose pull
  if errorlevel 1 goto pull_failed
) else (
  echo Starting sworkr. The first time it downloads it, which takes a few minutes...
)
docker compose up -d
if errorlevel 1 goto failed

echo Waiting for sworkr to answer...
where curl.exe >nul 2>&1
if errorlevel 1 (
  timeout /t 10 /nobreak >nul
  goto open
)
set /a tries=0
:wait_web
curl.exe -s -o nul --max-time 3 http://localhost:8008/api/health >nul 2>&1
if not errorlevel 1 goto open
timeout /t 2 /nobreak >nul
set /a tries+=1
if %tries% lss 60 goto wait_web
echo It's taking longer than usual. If the page doesn't load, wait a minute and refresh it.

:open
start "" http://localhost:8008
echo.
echo sworkr is running at http://localhost:8008
echo It keeps running in the background, and starts by itself whenever Docker Desktop starts.
if /i "%~1"=="update" (
  echo Up to date. Your records were kept, and a copy was saved before any upgrade.
  echo.
  pause
  exit /b 0
)
echo You can close this window.
timeout /t 10 >nul
exit /b 0

:pull_failed
echo.
echo Couldn't download the update. Check your internet connection and try again.
echo sworkr wasn't changed, and your records are safe.
echo.
pause
exit /b 1

:failed
echo.
echo sworkr couldn't start. The message above says why.
echo Help: sworkr.com/docs/troubleshooting.html
echo.
pause
exit /b 1

@echo off
REM Build the frontend, set up Python, and serve the app on http://localhost:8000
REM
REM   run.cmd
REM
REM Safe to re-run: it skips work that is already done.
REM Pass --clean to redo everything from scratch.

setlocal
cd /d "%~dp0"

if "%PORT%"=="" set PORT=8000
set VENV=.venv

where node >nul 2>&1 || (
  echo Node is not installed. Get it from https://nodejs.org ^(version 20 or newer^).
  exit /b 1
)
where python >nul 2>&1 || (
  echo Python is not installed. Get it from https://python.org ^(version 3.11 or newer^).
  exit /b 1
)

echo Vlada AI - embroidery fill
echo.

if "%1"=="--clean" (
  echo --clean: removing the virtualenv and previous build
  if exist "%VENV%" rmdir /s /q "%VENV%"
  if exist backend\static rmdir /s /q backend\static
  if exist frontend\node_modules rmdir /s /q frontend\node_modules
)

if not exist frontend\node_modules (
  echo 1/3  Installing frontend packages ^(a minute or so, once^)
  pushd frontend && call npm install --no-audit --no-fund || (popd & exit /b 1)
  popd
) else (
  echo 1/3  Frontend packages already installed
)

if not exist backend\static\index.html (
  echo 2/3  Building the frontend
  pushd frontend && call npm run build || (popd & exit /b 1)
  popd
) else (
  echo 2/3  Frontend already built ^(delete backend\static to rebuild^)
)

if not exist "%VENV%" (
  echo 3/3  Setting up Python and installing packages
  python -m venv "%VENV%" || exit /b 1
  "%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "%VENV%\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt || exit /b 1
) else (
  echo 3/3  Python packages already installed
)

echo.
echo Ready.  Open  -^>  http://localhost:%PORT%
echo Drop samples\Velvet.svg onto the page.  Press Ctrl+C to stop.
echo.

cd backend
"..\%VENV%\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

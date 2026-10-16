@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher ^(py^) was not found. Install Python 3.12 first.
    popd
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python 3.12 virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :failed
)

echo Installing the editable project and development tools...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :failed

if not exist ".env" copy /Y ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto :failed

echo Bootstrap complete. Start with scripts\run_dashboard.cmd.
popd
exit /b 0

:failed
echo Bootstrap failed. Review the command output above.
popd
exit /b 1

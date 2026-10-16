@echo off
setlocal
set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run scripts\bootstrap.cmd first.
    popd
    exit /b 1
)

".venv\Scripts\python.exe" -m office_hub
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%

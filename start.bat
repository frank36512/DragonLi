@echo off
cd /d "%~dp0"

set PYTHON=%~dp0.venv\Scripts\python.exe
if not exist "%PYTHON%" (
    echo [错误] 未找到虚拟环境: %PYTHON%
    echo 请先在项目根目录执行: python -m venv .venv
    echo 然后执行: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo 正在启动狸猫短剧...
"%PYTHON%" src\main.py %*

rem 异常退出时保留窗口查看日志
if errorlevel 1 (
    echo.
    echo 程序异常退出，请查看上方日志。
    pause
)

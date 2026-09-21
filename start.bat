@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"
title 编舟文心 - Windows 启动器

echo ============================================
echo   编舟文心 - Windows 启动器
echo ============================================
echo.

rem ================= 1. 查找 Python =================
set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    echo [错误] 没有检测到 Python。
    echo.
    echo   请先安装 Python 3.9 或更高版本：
    echo     https://www.python.org/downloads/windows/
    echo   安装时务必勾选 "Add Python to PATH"，装完重新双击本文件。
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('%PY_CMD% --version 2^>^&1') do set "PYVER=%%v"
echo [1/4] 已找到 %PYVER%

rem ================= 2. 虚拟环境 =================
set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"
rem 虚拟环境里存的是绝对路径，项目被移动或复制后会失效，所以先验证能否运行
set "VENV_OK="
if exist "%VPY%" (
    "%VPY%" -c "import sys" >nul 2>nul
    if not errorlevel 1 set "VENV_OK=1"
)
if not defined VENV_OK (
    if exist "%VENV%" (
        echo [2/4] 虚拟环境不可用（项目可能被移动过），正在重建...
        rmdir /s /q "%VENV%"
    ) else (
        echo [2/4] 首次运行，正在创建虚拟环境 .venv ...
    )
    %PY_CMD% -m venv "%VENV%"
    if not exist "%VPY%" (
        echo.
        echo [错误] 创建虚拟环境失败，请确认 Python 安装完整后重试。
        pause
        exit /b 1
    )
) else (
    echo [2/4] 虚拟环境已就绪
)

rem ================= 3. 安装依赖 =================
echo [3/4] 检查依赖（首次会下载，请耐心等待）...
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo       国内镜像不可用，改用默认源重试...
    "%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)
echo       依赖就绪

rem ================= 4. 补齐配置文件 =================
if not exist "notify_config.json" if exist "notify_config.example.json" copy /y "notify_config.example.json" "notify_config.json" >nul
if not exist "webdav_config.json" if exist "webdav_config.example.json" copy /y "webdav_config.example.json" "webdav_config.json" >nul
if not exist "data" mkdir "data"

rem ================= 5. 启动服务 =================
set "LANIP="
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /r /c:"IPv4"') do (
    if not defined LANIP set "LANIP=%%i"
)
if defined LANIP set "LANIP=%LANIP: =%"

echo.
echo [4/4] 启动服务...
echo.
echo    本机访问   : http://127.0.0.1:10015
if defined LANIP echo    局域网访问 : http://%LANIP%:10015
echo.
echo    关闭本窗口即可停止服务。
echo    在网页上点「重启应用」会关掉进程，本窗口会自动把它拉起来。
echo.

:loop
"%VPY%" run.py
echo.
echo [提示] 应用已退出，5 秒后自动重新启动...
echo        想彻底停止请直接关闭本窗口。
timeout /t 5 /nobreak >nul 2>nul
goto loop

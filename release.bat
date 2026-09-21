@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title 编舟文心 - 发版工具

echo ============================================
echo   编舟文心 - 一键发版
echo   打包 exe ^> 发布 Gitee Release ^> 更新 version.json ^> 推送
echo ============================================
echo.

rem ================= 0. 前置检查 =================
set "PY_CMD="
where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
    echo [错误] 需要 Python。先装 Python 并加入 PATH。
    pause & exit /b 1
)
git rev-parse --git-dir >nul 2>nul
if errorlevel 1 (
    echo [错误] 当前目录不是 git 仓库。
    pause & exit /b 1
)
if not defined GITEE_TOKEN (
    echo [提示] 未设置 GITEE_TOKEN 环境变量。
    set /p GITEE_TOKEN="请粘贴 Gitee 私人令牌: "
)
if not defined GITEE_TOKEN (
    echo [错误] 没有令牌，无法发布 Release。
    pause & exit /b 1
)

rem ================= 1. 读版本号 =================
set "VER="
for /f "tokens=2 delims== " %%a in ('findstr /r "__version__ *= *" app\core.py') do set "VER=%%~a"
if not defined VER (
    echo [错误] 无法从 app/core.py 读取版本号。
    pause & exit /b 1
)
set "VER=%VER:"=%"
echo [1/6] 当前版本: v%VER%

rem ================= 2. 打包 exe =================
echo [2/6] 打包 exe（首次约 1-3 分钟）...
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm --onefile --noconsole --name "编舟文心" ^
  --distpath dist --workpath build --specpath build ^
  --add-data "%~dp0templates;templates" ^
  --add-data "%~dp0static;static" ^
  --add-data "%~dp0locales;locales" ^
  --add-data "%~dp0config.yaml;." ^
  --add-data "%~dp0notify_config.example.json;." ^
  --add-data "%~dp0webdav_config.example.json;." ^
  --collect-submodules app --collect-submodules werss --collect-submodules jobs ^
  --hidden-import init_sys --hidden-import crawler --hidden-import paths ^
  --hidden-import webview.platforms.winforms --hidden-import clr ^
  launcher.py > build\release_build.log 2>&1
if not exist "dist\编舟文心.exe" (
    echo [错误] 打包失败，日志: build\release_build.log
    pause & exit /b 1
)
for %%F in ("dist\编舟文心.exe") do echo       完成: %%~zF 字节

rem ================= 3. 压缩 exe =================
echo [3/6] 压缩 exe 为 zip...
set "ZIP=WCAN_v%VER%.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\编舟文心.exe' -DestinationPath 'dist\%ZIP%' -Force"
if not exist "dist\%ZIP%" (
    echo [错误] 压缩失败。
    pause & exit /b 1
)
echo       已生成: dist\%ZIP%

rem ================= 4. 更新 version.json 并提交推送 =================
echo [4/6] 更新 version.json 并推送...
powershell -NoProfile -Command ^
  "$j = Get-Content version.json -Raw -Encoding UTF8 | ConvertFrom-Json;" ^
  "$j.version = '%VER%';" ^
  "$j.updated_at = Get-Date -Format 'yyyy-MM-dd';" ^
  "$j | ConvertTo-Json | Set-Content version.json -Encoding UTF8"
git add version.json
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "chore: release v%VER%"
) else (
    echo       version.json 无变化
)
git push origin main
if errorlevel 1 (
    echo [错误] git push 失败，中止（Release 不会发布）。
    pause & exit /b 1
)
echo       已推送

rem ================= 5. 发布 Gitee Release（先传附件再创建）=================
echo [5/6] 发布 Gitee Release v%VER%...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release_gitee.ps1" -Version "%VER%" -ZipPath "dist\%ZIP%" -Token "%GITEE_TOKEN%"
if errorlevel 1 (
    echo [错误] Release 发布失败，详见上方输出。代码已推送，可手动重试上传附件。
    pause & exit /b 1
)

echo [6/6] 完成！
echo.
echo   仓库 : https://gitee.com/AZSongguo/wcan
echo   发布 : https://gitee.com/AZSongguo/wcan/releases/tag/v%VER%
echo   部员侧: 打开应用 -^> 检查更新 -^> 会提示 v%VER% 并给出下载链接
echo.
pause

@echo off
chcp 65001 >nul
echo ========================================
echo   微信小店客服助手 - Windows 打包脚本
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

echo [1/4] 检查 Python 环境...
python -c "import sys; print(f'Python 版本：{sys.version}')"

REM 创建虚拟环境（如果不存在）
if not exist ".venv" (
    echo [2/4] 创建虚拟环境...
    python -m venv .venv
) else (
    echo [2/4] 虚拟环境已存在，跳过创建
)

REM 激活虚拟环境并安装依赖
echo [3/4] 安装依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

echo [4/4] 开始打包...
echo 这可能需要 2-5 分钟，请耐心等待...

REM 清理旧的构建文件
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM 运行 PyInstaller
pyinstaller --clean weixin_store.spec

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   打包成功完成！
    echo ========================================
    echo.
    echo 可执行文件位置：dist\微信小店客服助手\微信小店客服助手.exe
    echo.
    echo 你可以将整个 dist\微信小店客服助手 文件夹分发给用户
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo   打包失败，请检查错误信息
    echo ========================================
    pause
    exit /b 1
)

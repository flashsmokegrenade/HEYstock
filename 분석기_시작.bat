@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo         HEYstock Analysis System
echo ========================================================
echo.

:: Python Check
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b
)

:: Package Connect
echo [*] Checking package setup...
python -m pip install -e . >nul 2>&1

:RUN_LOOP
echo.
echo ---------------------------------------------------------
set /p TICKER="Enter Stock Ticker (e.g. TSLA, AAPL, NVDA): "
if "%TICKER%"=="" goto RUN_LOOP

echo.
echo [INFO] Running HEYstock for "%TICKER%"...
echo ---------------------------------------------------------
:: [핵심 수정] 공백이 포함된 종목명을 안전하게 전달하도록 큰따옴표("%TICKER%") 적용
python main.py --ticker "%TICKER%"
echo ---------------------------------------------------------
echo [INFO] Analysis completed.
echo.

:AGAIN_LOOP
set /p AGAIN="Do you want to analyze another stock? (Y/N): "
if /i "%AGAIN%"=="Y" goto RUN_LOOP
if /i "%AGAIN%"=="N" goto EXIT_PROG

:: Y/N 대신 바로 다음 종목명을 쳤을 때 종료되지 않고 즉시 분석 루프로 연결
if not "%AGAIN%"=="" (
    set "TICKER=%AGAIN%"
    echo.
    echo [INFO] Running HEYstock for "%TICKER%"...
    echo ---------------------------------------------------------
    python main.py --ticker "%TICKER%"
    echo ---------------------------------------------------------
    echo [INFO] Analysis completed.
    echo.
    goto AGAIN_LOOP
)

:EXIT_PROG
echo Closing program...
pause
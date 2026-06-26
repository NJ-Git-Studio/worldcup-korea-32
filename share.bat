@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 월드컵 경우의 수 - 공유 서버

echo ============================================================
echo   월드컵 2026 한국 32강 경우의 수 - 공개 링크 공유
echo ============================================================
echo.

REM --- cloudflared 경로 찾기 (PATH 별칭 우선, 없으면 winget 설치 위치) ---
set "CF=cloudflared"
where cloudflared >nul 2>nul
if errorlevel 1 (
  for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Microsoft\WinGet\Packages\cloudflared.exe" 2^>nul') do set "CF=%%i"
)

REM --- Flask 앱을 별도 창에서 실행 ---
echo [1/2] 대시보드 서버를 시작합니다...
start "worldcup-dashboard" /min cmd /c "python app.py"

echo       서버 준비 대기 (6초)...
timeout /t 6 /nobreak >nul

echo.
echo [2/2] 공개 링크(터널)를 생성합니다.
echo.
echo   아래에 표시되는  https://...trycloudflare.com  주소를
echo   친구에게 카톡/메일로 보내면 누구나 접속할 수 있습니다.
echo.
echo   * 이 창과 서버 창을 닫으면 공유가 종료됩니다.
echo   * 본인 PC가 켜져 있는 동안에만 접속됩니다.
echo ------------------------------------------------------------
echo.

"%CF%" tunnel --url http://localhost:5000 --no-autoupdate

echo.
echo 공유가 종료되었습니다. 아무 키나 누르세요.
pause >nul

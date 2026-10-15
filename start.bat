@echo off
setlocal
cd /d "%~dp0"

title AI 테마주 인사이트 리포트

if not exist "venv\Scripts\python.exe" goto ERR_VENV
if not exist ".env" goto ERR_ENV
if not exist "src\ui\app.py" goto ERR_APP

echo ===================================================
echo   AI 테마주 인사이트 리포트 - Streamlit 실행
echo ===================================================
echo [안내] 가상환경 및 환경설정을 확인했습니다.
echo [안내] Streamlit 웹 서버를 시작합니다...
echo [안내] 브라우저가 열리면 테마를 입력해 리포트를 생성하세요.
echo [안내] 종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo ===================================================
echo.

".\venv\Scripts\python.exe" -m streamlit run ".\src\ui\app.py"
goto END

:ERR_VENV
echo.
echo [오류] Python 가상환경 venv 폴더를 찾을 수 없습니다.
echo venv\Scripts\python.exe 경로를 확인해주세요.
echo.
pause
exit /b 1

:ERR_ENV
echo.
echo [경고] .env 설정 파일이 없습니다.
echo .env.example 파일을 복사하여 .env 파일을 생성하고 API 키를 입력해주세요.
echo.
pause
exit /b 1

:ERR_APP
echo.
echo [오류] 실행 대상 파일 src\ui\app.py 를 찾을 수 없습니다.
echo.
pause
exit /b 1

:END
if errorlevel 1 (
    echo.
    echo [알림] 프로그램이 오류와 함께 종료되었습니다.
    pause
)

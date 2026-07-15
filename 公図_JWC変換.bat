@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: 引数なし → 使い方を表示
if "%~1"=="" (
    echo.
    echo  公図_JWC変換.bat
    echo  ─────────────────────────────────────────
    echo  公図PDFをこのファイルにドロップすると
    echo  JWCファイルに変換して同フォルダに保存します。
    echo.
    echo  使い方:
    echo    1) 公図PDFをこの .bat にドラッグ＆ドロップ
    echo    2) または: 公図_JWC変換.bat "C:\path\to\kouzu.pdf"
    echo.
    echo  オプション（コマンドラインから実行時）:
    echo    --scale 500    縮尺を指定（省略時: PDF内から自動検出）
    echo    --format dxf   DXF形式で出力（省略時: JWC）
    echo.
    pause
    exit /b
)

:: 複数ファイルを順番に処理
set OK=0
set NG=0

:loop
if "%~1"=="" goto :done

set "PDF=%~1"
echo 変換中: %~nx1

python "%~dp0scripts\kouzu_to_jwc.py" "%PDF%"
if !ERRORLEVEL! equ 0 (
    set /a OK+=1
    echo   完了: %~dpn1.jwc
) else (
    set /a NG+=1
    echo   [エラー] 変換に失敗しました
)
echo.
shift
goto :loop

:done
echo ─────────────────────────────────────────
echo  処理結果: 成功 !OK! 件 / 失敗 !NG! 件
echo ─────────────────────────────────────────
pause

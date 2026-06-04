@echo off
cd /d "%~dp0"
chcp 65001 > nul

:: Python確認
python --version > nul 2>&1
if errorlevel 1 (
    echo ============================================
    echo  Python が見つかりません。
    echo  https://www.python.org/ から Python 3.10以上を
    echo  インストールしてから再度実行してください。
    echo ============================================
    pause
    exit /b 1
)

:: パッケージ確認・インストール（初回のみ時間がかかります）
python -c "import customtkinter, pdfplumber, tkinterdnd2" > nul 2>&1
if errorlevel 1 (
    echo 必要なパッケージをインストールしています（初回のみ）...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo インストールに失敗しました。管理者権限で再実行してください。
        pause
        exit /b 1
    )
)

:: アプリ起動
pythonw app.py
if errorlevel 1 (
    echo 起動エラーが発生しました。
    python app.py
    pause
)

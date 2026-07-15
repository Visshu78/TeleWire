Write-Host "==========================================" -ForegroundColor Green
Write-Host "TeleIntel Ingestion Sandbox Dev Bootstrap" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

# 1. Virtual Environment Setup
if (-not (Test-Path ".venv")) {
    Write-Host "[*] Creating virtual environment (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
}

# 2. Dependency Installation
Write-Host "[*] Upgrading pip and installing dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Database Migrations Check
if (Test-Path "migrate_db.py") {
    Write-Host "[*] Initializing and validating database migrations..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe migrate_db.py
}

# 4. Verification Tests
Write-Host "[*] Running comprehensive unit test validation suite..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m unittest discover -s tests

Write-Host "==========================================" -ForegroundColor Green
Write-Host "[+] TeleIntel bootstrap completed successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:DATA_DIR = Join-Path $PSScriptRoot 'data'
if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Worker dependency installation failed.' }
$launchArgs = @('-m', 'uvicorn', 'control_api:app', '--host', '127.0.0.1', '--port', '8787')
if (Test-Path -LiteralPath '.env') { $launchArgs += @('--env-file', '.env') }
& ./.venv/Scripts/python.exe @launchArgs
exit $LASTEXITCODE

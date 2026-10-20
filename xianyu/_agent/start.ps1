param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
. (Join-Path $projectRoot 'scripts/runtime.ps1')
$workerRoot = Join-Path $projectRoot 'services/xianyu-worker'
$pythonExe = Join-Path $workerRoot '.venv/Scripts/python.exe'
$nodeExe = (Get-Command node -ErrorAction Stop).Source
$frontCli = Join-Path $projectRoot 'node_modules/vinext/dist/cli.js'
if (!(Test-Path -LiteralPath $pythonExe) -or !(Test-Path -LiteralPath $frontCli)) {
    throw 'Dependencies missing. Run services/xianyu-worker/run.ps1 and start-dashboard.ps1 first.'
}
$logRoot = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

function Start-LocalService($Port, $Executable, $Arguments, $Directory, $Name) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if (!$owner -or (($owner.ExecutablePath -notlike "$projectRoot\*") -and ($owner.CommandLine -notlike "*$projectRoot*"))) {
            throw "Port $Port is occupied by another service (PID $($listener.OwningProcess)). Stop it before starting this project."
        }
        Write-Host "$Name already running (PID $($listener.OwningProcess))."
        return
    }
    $service = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$Name.out.log") -RedirectStandardError (Join-Path $logRoot "$Name.err.log")
    Write-Host "Started $Name (PID $($service.Id))."
}

$env:PYTHONUTF8 = '1'
$env:DATA_DIR = Join-Path $workerRoot 'data'
$workerArgs = @('-m', 'uvicorn', 'control_api:app', '--host', '127.0.0.1', '--port', '8787')
if (Test-Path -LiteralPath (Join-Path $workerRoot '.env')) { $workerArgs += @('--env-file', '.env') }
Start-LocalService 8787 $pythonExe $workerArgs $workerRoot 'worker'
Start-LocalService 3000 $nodeExe @(('"{0}"' -f $frontCli), 'dev', '--host', '127.0.0.1', '--port', '3000', '--strictPort') $projectRoot 'dashboard'

foreach ($url in @('http://127.0.0.1:8787/health', 'http://127.0.0.1:3000')) {
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (!$ready) { throw "Service did not become ready: $url. See $logRoot." }
}
Write-Host 'Ready: http://127.0.0.1:3000'
if (!$NoBrowser) { Start-Process 'http://127.0.0.1:3000' }

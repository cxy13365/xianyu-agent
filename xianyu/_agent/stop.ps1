$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
foreach ($port in @(3000, 8787)) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($owner -and (($owner.ExecutablePath -like "$projectRoot\*") -or ($owner.CommandLine -like "*$projectRoot*"))) {
            Stop-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
            Write-Host "Stopped service on port $port."
        } else {
            Write-Host "Port $port belongs to another project; left running."
        }
    }
}

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts/runtime.ps1')
if (!(Test-Path -LiteralPath 'node_modules/vinext/dist/cli.js')) {
    & pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
}
& node node_modules/vinext/dist/cli.js dev --host 127.0.0.1 --port 3000 --strictPort
exit $LASTEXITCODE

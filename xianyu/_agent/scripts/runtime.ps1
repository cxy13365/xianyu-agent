# Prefer installed runtimes; support the existing Codex bundled runtime as fallback.
$bundledRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    $nodeBin = Join-Path $bundledRoot 'node/bin'
    if (Test-Path -LiteralPath (Join-Path $nodeBin 'node.exe')) { $env:PATH = "$nodeBin;$env:PATH" }
}
if (!(Get-Command pnpm -ErrorAction SilentlyContinue)) {
    $pnpmBin = Join-Path $bundledRoot 'bin/fallback'
    if (Test-Path -LiteralPath (Join-Path $pnpmBin 'pnpm.cmd')) { $env:PATH = "$pnpmBin;$env:PATH" }
}
if (!(Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 22.13+ is required.' }

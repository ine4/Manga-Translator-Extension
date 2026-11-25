param([string]$PythonExe = "python")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$controller = Join-Path $PSScriptRoot 'target\release\manga-local.exe'
$env:MANGA_LOCAL_MODELS = Join-Path $PSScriptRoot 'models'
$env:MANGA_LLAMA_SERVER = Join-Path $PSScriptRoot 'runtime\llama-server.exe'
$localProcess = $null
try {
    $alreadyRunning = $false
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:7678/local/models' -Headers @{'X-Manga-Local'='1'} -TimeoutSec 2
        $alreadyRunning = $true
    } catch {}
    if (-not $alreadyRunning -and (Test-Path $controller)) {
        $localProcess = Start-Process -FilePath $controller -WorkingDirectory $root -NoNewWindow -PassThru
        Write-Host 'Rust local controller started (no translation model loaded).'
    } elseif (-not $alreadyRunning) {
        Write-Warning 'Local controller not built. Run setup-local-ai.bat once. Existing cloud mode remains available.'
    }
    Push-Location (Join-Path $root 'backend')
    try { & $PythonExe main.py } finally { Pop-Location }
} finally {
    if ($localProcess -and -not $localProcess.HasExited) {
        # Terminate the whole owned process tree, including an active inference worker.
        & taskkill.exe /PID $localProcess.Id /T /F | Out-Null
    }
}

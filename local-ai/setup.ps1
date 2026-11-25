param([string]$PythonExe = "python")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# Pinned official CUDA 12.4 release. Verify the published SHA-256 before extraction.
$tag = 'b12644'
$assets = [ordered]@{
    "llama-b12644-bin-win-cuda-12.4-x64.zip" = "b72264d4a3222828ce9c6a818e38766797948f8503742b217937bfc823929a5d"
    "cudart-llama-bin-win-cuda-12.4-x64.zip" = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Install Rust stable (MSVC toolchain) and Visual Studio C++ Build Tools, then rerun setup."
}
& cargo build --release --manifest-path (Join-Path $PSScriptRoot 'Cargo.toml')
if ($LASTEXITCODE -ne 0) { throw "Rust controller build failed" }
$runtime = Join-Path $PSScriptRoot 'runtime'
if (-not (Test-Path (Join-Path $runtime 'llama-server.exe'))) {
    $stage = Join-Path ([IO.Path]::GetTempPath()) ("manga-ai-install-" + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        $n = 0
        foreach ($asset in $assets.Keys) {
            $zip = Join-Path $stage $asset
            Write-Host "Downloading official $asset"
            Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/ggml-org/llama.cpp/releases/download/$tag/$asset" -OutFile $zip
            if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $assets[$asset]) {
                throw "Hash mismatch: $asset"
            }
            $n++
            Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $stage "unpacked-$n") -Force
        }
        $exe = Get-ChildItem (Join-Path $stage 'unpacked-1') -Recurse -Filter llama-server.exe | Select-Object -First 1
        if (-not $exe) { throw "llama-server.exe not found in release" }
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        Copy-Item (Join-Path $exe.Directory.FullName '*') -Destination $runtime -Recurse -Force
        Get-ChildItem (Join-Path $stage 'unpacked-2') -Recurse -Filter '*.dll' | Copy-Item -Destination $runtime -Force
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
& $PythonExe -c "import huggingface_hub"
if ($LASTEXITCODE -ne 0) {
    & $PythonExe -m pip install "huggingface_hub>=0.24.0"
    if ($LASTEXITCODE -ne 0) { throw "Hugging Face dependency installation failed" }
}
& $PythonExe (Join-Path $PSScriptRoot 'model_manager.py') install-default
if ($LASTEXITCODE -ne 0) { throw "Default model download failed" }
Write-Host 'Local AI setup complete. Launch start-backend.bat.'

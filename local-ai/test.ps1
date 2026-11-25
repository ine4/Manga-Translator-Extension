param([string]$PythonExe = "python", [switch]$Live)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
function CheckExit($what) { if($LASTEXITCODE -ne 0){throw "$what failed (exit $LASTEXITCODE)"} }
& cargo test --manifest-path (Join-Path $PSScriptRoot 'Cargo.toml')
CheckExit 'Rust lease/catalog tests'
& $PythonExe -m compileall -q (Join-Path $root 'backend') (Join-Path $PSScriptRoot 'model_manager.py')
CheckExit 'Python compile'
& $PythonExe -m unittest discover -s (Join-Path $root 'backend\tests')
CheckExit 'Python integration tests'
& $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'tests')
CheckExit 'Hugging Face model catalog tests'
Push-Location (Join-Path $root 'extension')
try {
    & npm.cmd ci
    CheckExit 'npm ci'
    & npm.cmd run build
    CheckExit 'Extension TypeScript/build'
    & node --experimental-strip-types --test tests/local-ai.test.mts
    CheckExit 'Extension lease/routing tests (Node 22+)'
} finally {Pop-Location}
# Static guard against the former temporary-file and persisted browser image paths.
$forbidden = Select-String -Path (Join-Path $root 'backend\pipeline\wrapper.py'),(Join-Path $root 'backend\core\image\*.py'),(Join-Path $root 'backend\core\outside_text_processor.py') -Pattern 'NamedTemporaryFile|mkstemp|cv2\.imwrite'
if($forbidden){throw 'Unexpected image temp-file or imwrite call: inspect matches'}
$persisted = Select-String -Path (Join-Path $root 'extension\src\content-script\index.ts') -Pattern 'storage\.local\.set|saveTranslatedCacheEntry|indexedDB'
if($persisted){throw 'Unexpected content-script persistence path'}
if($Live){
    & $PythonExe (Join-Path $PSScriptRoot 'smoke.py')
    CheckExit 'Live CUDA smoke'
}
Write-Host 'Requested checks passed.'

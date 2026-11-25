param([string]$PythonExe = "python")
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'model_manager.py'
$headers = @{'X-Manga-Local'='1'}
$root = 'http://127.0.0.1:7678'
$lease = 'gui:' + [Guid]::NewGuid().ToString()
$script:pinned = $null
$script:download = $null
$form = New-Object Windows.Forms.Form
$form.Text = 'MangaTranslator - Local Model Manager'
$form.Size = New-Object Drawing.Size(720, 565)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object Drawing.Font('Segoe UI', 10)
function Label($text,$x,$y,$w=650) {
    $l = New-Object Windows.Forms.Label
    $l.Text=$text; $l.Location=New-Object Drawing.Point($x,$y)
    $l.Size=New-Object Drawing.Size($w,23)
    $form.Controls.Add($l)
    return $l
}
function TextBox($x,$y,$w,$value='') {
    $t=New-Object Windows.Forms.TextBox; $t.Location=New-Object Drawing.Point($x,$y)
    $t.Size=New-Object Drawing.Size($w,27); $t.Text=$value
    $form.Controls.Add($t); return $t
}
function Combo($x,$y,$w) {
    $c=New-Object Windows.Forms.ComboBox; $c.Location=New-Object Drawing.Point($x,$y)
    $c.Size=New-Object Drawing.Size($w,27); $c.DropDownStyle='DropDownList'
    $form.Controls.Add($c); return $c
}
function Button($text,$x,$y,$w,$action) {
    $b=New-Object Windows.Forms.Button
    $b.Text=$text; $b.Location=New-Object Drawing.Point($x,$y)
    $b.Size=New-Object Drawing.Size($w,32)
    $b.Add_Click($action); $form.Controls.Add($b)
}
function Api($route,$body=$null,$timeout=4) {
    if ($null -eq $body) { return Invoke-RestMethod -Uri "$root$route" -Headers $headers -TimeoutSec $timeout }
    return Invoke-RestMethod -Uri "$root$route" -Headers $headers -Method Post -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress) -TimeoutSec $timeout
}
$null=Label 'Registered local vision models' 15 15
$models=Combo 15 42 660
$status=Label 'Start start-backend.bat to connect.' 15 78
$script:catalog=@()
function RefreshModels {
    try {
        $selected = $models.SelectedIndex
        $oldId = if ($selected -ge 0 -and $selected -lt $script:catalog.Count) {$script:catalog[$selected].id} else {$null}
        $result=Api '/local/models'
        $script:catalog=@($result.models)
        $models.Items.Clear()
        $newIndex=0
        for ($i=0;$i -lt $script:catalog.Count;$i++) {
            $m=$script:catalog[$i]
            $state=if($m.installed){'Installed'}else{'Not installed'}
            $null=$models.Items.Add("$($m.label) - $state")
            if($m.id -eq $oldId){$newIndex=$i}
        }
        if($models.Items.Count){$models.SelectedIndex=$newIndex}
        $status.Text=if($result.loaded_model){"In VRAM: $($result.loaded_model) | leases: $($result.leases)"}else{'Translation model unloaded (SSD)'}
        if(-not $result.engine_available){$status.Text='CUDA engine missing. Run setup-local-ai.bat.'}
    } catch {$status.Text='Controller offline or busy. Retry.'}
}
function SelectedId {
    if($models.SelectedIndex -lt 0){throw 'Select a model first'}
    return $script:catalog[$models.SelectedIndex].id
}
function ReleasePin {
    try {$null=Api '/local/lease' @{id=$lease;keep=$false} 10} catch {}
    $script:pinned=$null
}
function RunDownload($argv) {
    if($script:download -and -not $script:download.HasExited){throw 'Download already in progress'}
    # Repo, ID and filenames are validated below; quote the local script path.
    $script:download=Start-Process -FilePath $PythonExe -ArgumentList (@('"' + $installer + '"') + $argv) -PassThru
    $status.Text='Download running in its own console. Refresh when complete.'
}
Button 'Refresh' 15 108 100 {RefreshModels}
Button 'Load for GUI session' 125 108 185 {
    try {
        $id=SelectedId
        $status.Text='Loading model into VRAM...'; $form.Refresh()
        $null=Api '/local/lease' @{id=$lease;model=$id;keep=$true} 150
        $script:pinned=$id; RefreshModels
    } catch {$status.Text='Load failed: install model, release other pins, or check CUDA.'}
}
Button 'Release GUI pin' 320 108 150 {ReleasePin;RefreshModels}
Button 'Remove selected' 480 108 195 {
    try {
        $id=SelectedId
        if([Windows.Forms.MessageBox]::Show("Delete model files for $id?",'Confirm removal','YesNo') -eq 'Yes'){
            $null=Api '/local/remove' @{id=$id} 15
            RefreshModels
        }
    } catch {$status.Text='Cannot remove: release pins and wait for active translation.'}
}
Button 'Install default Qwen 4B' 15 151 240 {
    try {RunDownload @('install-default')} catch {$status.Text=$_.Exception.Message}
}
$null=Label 'Add a compatible vision GGUF model from Hugging Face' 15 205
$repo=TextBox 15 231 660 'https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF'
$null=Label 'Model ID (letters/numbers, hyphen, underscore)' 15 264
$modelId=TextBox 15 290 465 'custom-vlm'
$weights=Combo 15 351 660
$projector=Combo 15 410 660
$null=Label 'Language model GGUF' 15 326
$null=Label 'Vision projector GGUF (mmproj)' 15 385
function ValidRepo {
    if($repo.Text -notmatch '^(https://huggingface\.co/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$'){throw 'Enter a Hugging Face repository URL or owner/name'}
    return $repo.Text.TrimEnd('/')
}
Button 'Find GGUF files' 490 287 185 {
    try {
        $r=ValidRepo
        $status.Text='Retrieving model file list...';$form.Refresh()
        $names=@((& $PythonExe $installer files $r | Out-String | ConvertFrom-Json))
        if($LASTEXITCODE -ne 0){throw 'Could not list repository'}
        $weights.Items.Clear(); $projector.Items.Clear()
        foreach($name in $names){
            if($name -match '(?i)mmproj'){ $null=$projector.Items.Add($name) }
            else {$null=$weights.Items.Add($name)}
        }
        if($weights.Items.Count){$weights.SelectedIndex=0}
        if($projector.Items.Count){$projector.SelectedIndex=0}
        $status.Text='Select compatible weights and projector from the same repository.'
    } catch {$status.Text='Unable to list files. Check repository and Hugging Face dependency.'}
}
Button 'Install selected model' 15 452 230 {
    try {
        $r=ValidRepo
        if($modelId.Text -notmatch '^[A-Za-z0-9_-]{1,80}$'){throw 'Invalid model ID'}
        if($weights.SelectedIndex -lt 0 -or $projector.SelectedIndex -lt 0){throw 'Select weights and projector'}
        RunDownload @('install',$modelId.Text,$r,[string]$weights.SelectedItem,[string]$projector.SelectedItem)
    } catch {$status.Text=$_.Exception.Message}
}
$timer=New-Object Windows.Forms.Timer
$timer.Interval=25000
$timer.Add_Tick({
    if($script:pinned){
        try {$null=Api '/local/lease' @{id=$lease;model=$script:pinned;keep=$true} 5} catch {}
    }
    if($script:download -and $script:download.HasExited){$script:download=$null}
    RefreshModels
})
$form.Add_FormClosing({$timer.Stop();ReleasePin})
RefreshModels
$timer.Start()
[void]$form.ShowDialog()

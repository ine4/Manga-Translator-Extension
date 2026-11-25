param([string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
# Run the real form and click its real handlers after the window is shown.
$source = Get-Content -Raw (Join-Path $PSScriptRoot 'manager.ps1')
$source = $source.Replace('$PSScriptRoot', ("'" + $PSScriptRoot.Replace("'", "''") + "'"))
$checks = @'
$form.Add_Shown({
    try {
        if (-not $form.Visible -or $models.Items.Count -lt 1) { throw 'Model catalog not visible' }
        if (-not $script:catalog[0].installed) { throw 'Install default before GUI checks' }
        $load = $form.Controls | Where-Object { $_ -is [Windows.Forms.Button] -and $_.Text -eq 'Load for GUI session' }
        $release = $form.Controls | Where-Object { $_ -is [Windows.Forms.Button] -and $_.Text -eq 'Release GUI pin' }
        $list = $form.Controls | Where-Object { $_ -is [Windows.Forms.Button] -and $_.Text -eq 'Find GGUF files' }
        $install = $form.Controls | Where-Object { $_ -is [Windows.Forms.Button] -and $_.Text -eq 'Install selected model' }
        $default = $form.Controls | Where-Object { $_ -is [Windows.Forms.Button] -and $_.Text -eq 'Install default Qwen 4B' }
        $load.PerformClick()
        if (-not $script:pinned -or (Api '/local/models').loaded_model -ne $script:pinned) { throw 'GUI load failed' }
        $release.PerformClick()
        if ($script:pinned -or (Api '/local/models').loaded_model) { throw 'GUI release failed' }
        Write-Host 'PASS: visible GUI catalog, load and release handlers'
        $list.PerformClick()
        if ($weights.Items.Count -lt 1 -or $projector.Items.Count -lt 1) { throw 'HF dropdowns did not populate' }
        $modelId.Text = '../invalid'
        $install.PerformClick()
        if ($status.Text -ne 'Invalid model ID') { throw 'GUI accepted invalid ID' }
        $repo.Text = 'https://example.invalid/not-a-model'
        $list.PerformClick()
        if ($status.Text -notlike 'Unable to list files*') { throw 'GUI accepted non-HF URL' }
        Write-Host 'PASS: real GUI HF listing and invalid input handlers'
        $script:probeTicks = 0
        $probe = New-Object Windows.Forms.Timer
        $probe.Interval = 10
        $probe.Add_Tick({ $script:probeTicks++ })
        $probe.Start()
        $default.PerformClick()
        $until = [DateTime]::UtcNow.AddSeconds(2)
        while ([DateTime]::UtcNow -lt $until) {
            [Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 10
        }
        $probe.Stop()
        $probe.Dispose()
        if (-not $script:download -or $script:probeTicks -lt 1 -or -not $form.Enabled) { throw 'GUI did not remain responsive during download action' }
        Write-Host 'PASS: default installer runs separately while the GUI message loop stays responsive'
        $script:guiPassed = $true
    } catch {
        $script:guiFailure = $_
    } finally {
        $form.Close()
    }
})
[void]$form.ShowDialog()
if ($script:guiFailure) { throw $script:guiFailure }
if (-not $script:guiPassed) { throw 'GUI checks did not execute' }
'@
$source = $source.Replace('[void]$form.ShowDialog()', $checks)
& ([scriptblock]::Create($source)) -PythonExe $PythonExe

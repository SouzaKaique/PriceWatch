# PRICE WATCH - inicia o backend automaticamente quando voce entra no Windows.
# Cria uma tarefa no Agendador de Tarefas do Windows, so para o seu usuario (nao precisa de administrador).
$ErrorActionPreference = 'Stop'
$taskName = 'PRICE WATCH Backend'
$backend  = (Resolve-Path "$PSScriptRoot\..\backend").Path
$pythonw  = Join-Path $backend '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Ambiente Python nao encontrado em $pythonw. Rode a instalacao do README primeiro." }

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument 'run.py' -WorkingDirectory $backend
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'API e monitoramento de precos do PRICE WATCH (local)' -Force | Out-Null
Write-Host "Tarefa '$taskName' criada. O backend iniciara automaticamente no proximo logon."
Write-Host "Para iniciar agora: Start-ScheduledTask -TaskName '$taskName'"

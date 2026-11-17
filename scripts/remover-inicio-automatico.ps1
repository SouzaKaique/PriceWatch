# PRICE WATCH - remove a inicializacao automatica criada por instalar-inicio-automatico.ps1
$taskName = 'PRICE WATCH Backend'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Tarefa '$taskName' removida."
} else {
    Write-Host "Tarefa '$taskName' nao existe."
}

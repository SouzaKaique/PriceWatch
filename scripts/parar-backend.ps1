# PRICE WATCH - encerra o backend (usa o PID gravado em backend\instance\pricewatch.pid).
$pidFile = Join-Path (Resolve-Path "$PSScriptRoot\..\backend").Path 'instance\pricewatch.pid'
if (-not (Test-Path $pidFile)) { Write-Host 'Backend do PRICE WATCH nao esta em execucao.'; exit 0 }
$procId = [int](Get-Content $pidFile -Raw)
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
if ($proc -and $proc.ProcessName -like 'python*') {
    Stop-Process -Id $procId -Force
    Write-Host "Backend encerrado (PID $procId)."
} else {
    Write-Host 'Backend nao estava em execucao (PID antigo).'
}
Remove-Item $pidFile -ErrorAction SilentlyContinue

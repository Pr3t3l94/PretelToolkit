<#
  Compila PretelToolkit.exe a partir de src\setup_pc.pyw.

  Uso (desde cualquier carpeta):
    powershell -ExecutionPolicy Bypass -File src\compilar.ps1
    powershell -ExecutionPolicy Bypass -File src\compilar.ps1 -NoDeploy   # compila pero no sustituye el .exe
    powershell -ExecutionPolicy Bypass -File src\compilar.ps1 -Consola    # .exe con consola (ver errores)

  Requisitos: Python 3.10+ con tkinter (el instalador de python.org lo trae) e Internet
  la primera vez (descarga PyInstaller en un entorno virtual en
  %LOCALAPPDATA%\PretelToolkit-build; se puede borrar esa carpeta cuando quieras).
  Prueba los Python que encuentre hasta dar con uno que genere un .exe con tkinter
  (algunos Python "portables" hacen que PyInstaller lo deje fuera).
  Antes de sustituir el .exe guarda la version anterior como PretelToolkit.exe.bak
  (una sola copia, se renueva en cada despliegue). El original v3.0.0 esta aparte en
  src\original\ y este script nunca lo toca.
#>
param([switch]$NoDeploy, [switch]$Consola)

$ErrorActionPreference = 'Stop'
$src  = $PSScriptRoot
$root = Split-Path $src -Parent
# Entorno y carpeta de trabajo FUERA del kit y en una ruta sin espacios: con un espacio en
# la ruta del entorno virtual, PyInstaller deja tkinter fuera del .exe.
$buildRoot = Join-Path $env:LOCALAPPDATA 'PretelToolkit-build'
$venv = Join-Path $buildRoot 'venv'
$work = Join-Path $buildRoot 'work'
$dist = Join-Path $work 'dist'
$mode = if ($Consola) { '--console' } else { '--windowed' }

# 1) Candidatos: Python del PATH (sin el atajo de la Microsoft Store) y los de uso habitual
$candidates = @()
foreach ($name in 'py', 'python', 'python3') {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') { $candidates += $cmd.Source }
}
$candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python", "$env:APPDATA\uv\python", "$env:USERPROFILE\.local\bin" `
    -Include 'python.exe', 'python3*.exe' -Recurse -Depth 3 -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch 't\.exe$|w\.exe$' -and $_.FullName -notmatch '\\Lib\\|\\Scripts\\|\\venv\\' } |
    ForEach-Object FullName
$candidates = $candidates | Select-Object -Unique

function Test-Candidate($python) {
    # cmd evita que el stderr de Python se convierta en error de PowerShell
    cmd /c "`"$python`" -c `"import tkinter, venv`" >nul 2>nul"
    return ($LASTEXITCODE -eq 0)
}

function Build-With($python) {
    if (Test-Path $venv) { Remove-Item $venv -Recurse -Force }
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { return "no se pudo crear el entorno virtual" }
    $venvPy = Join-Path $venv 'Scripts\python.exe'
    & $venvPy -m pip install --quiet --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { return "no se pudo instalar PyInstaller (se necesita Internet)" }
    & $venvPy -m PyInstaller --noconfirm --clean --onefile $mode --name PretelToolkit `
        --icon (Join-Path $root 'assets\icon.ico') `
        --distpath $dist --workpath (Join-Path $work 'build') --specpath $work `
        (Join-Path $src 'setup_pc.pyw') | Out-Null
    if ($LASTEXITCODE -ne 0) { return "PyInstaller fallo" }
    $warn = Join-Path $work 'build\PretelToolkit\warn-PretelToolkit.txt'
    if ((Test-Path $warn) -and (Select-String -Path $warn -Pattern 'missing module named tkinter' -Quiet)) {
        return "el .exe habria quedado sin tkinter"
    }
    if (-not (Test-Path (Join-Path $dist 'PretelToolkit.exe'))) { return "no se genero el .exe" }
    return $null
}

$built = $null
foreach ($python in $candidates) {
    if (-not (Test-Candidate $python)) { continue }
    Write-Host "Probando Python: $python"
    $problem = Build-With $python
    if (-not $problem) { $built = Join-Path $dist 'PretelToolkit.exe'; break }
    Write-Host "  descartado: $problem"
}
if (-not $built) { throw 'No se pudo compilar con ningun Python. Instala Python desde python.org (con tcl/tk) y reintenta.' }
Write-Host ("Compilado: {0} ({1:N1} MB)" -f $built, ((Get-Item $built).Length / 1MB))

# 2) Desplegar
if ($NoDeploy) { Write-Host 'Modo -NoDeploy: no se ha sustituido el .exe.'; return }
$target = Join-Path $root 'PretelToolkit.exe'
if (Get-Process -Name PretelToolkit -ErrorAction SilentlyContinue) {
    throw 'PretelToolkit esta en ejecucion: cierralo y vuelve a lanzar este script.'
}
if (Test-Path $target) { Copy-Item $target "$target.bak" -Force }
Copy-Item $built $target -Force
Write-Host "Desplegado en $target (copia anterior: PretelToolkit.exe.bak)"

# Aviso: si la carpeta lleva una etiqueta de integridad BAJA heredable (la ponen algunos
# entornos aislados, p. ej. el de Claude Code), el .exe nuevo la hereda y Windows lo ejecuta
# como proceso de integridad baja: "Could not create temporary directory!".
$acl = (icacls $target) -join "`n"
if ($acl -match 'Nivel obligatorio bajo|Low Mandatory Level') {
    Write-Warning "El .exe ha heredado una etiqueta de integridad BAJA de la carpeta y no arrancara."
    Write-Warning "Arreglo: copia PretelToolkit.exe con el Explorador a otra carpeta, o ejecuta en tu consola:"
    Write-Warning "  icacls `"$target`" /setintegritylevel M"
}

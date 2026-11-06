<#
One-line installer for Windows 10/11 (run in PowerShell, as your normal user, no administrator needed):

  irm https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/install.ps1 | iex

To try it with simulated devices instead of a real installation (empty database only):

  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/install.ps1))) -Demo

It downloads the release archive from GitHub, builds a Python environment in
%LOCALAPPDATA%\GreenhouseControlCenter, and adds Desktop and Start-menu shortcuts. Read it before running.
Requires Python 3.11 or newer (winget install -e --id Python.Python.3.12). Re-running upgrades in place; data is kept.
Environment overrides (mainly for testing): GCC_VERSION, GCC_ARCHIVE (local .tar.gz), GCC_INSTALL_DIR, GCC_DESKTOP_DIR.
#>
param([switch]$Demo, [switch]$Network)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'unupunct/GREENHOUSE-CONTROL-CENTER'
$Version = if ($env:GCC_VERSION) { $env:GCC_VERSION } else { '0.9.2' }
$Dir = if ($env:GCC_INSTALL_DIR) { $env:GCC_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'GreenhouseControlCenter' }
$Desktop = if ($env:GCC_DESKTOP_DIR) { $env:GCC_DESKTOP_DIR } else { [Environment]::GetFolderPath('Desktop') }
$StartMenu = if ($env:GCC_DESKTOP_DIR) { $null } else { Join-Path ([Environment]::GetFolderPath('Programs')) '' }
$BindHost = if ($Network) { '0.0.0.0' } else { '127.0.0.1' }
$Name = 'Greenhouse Control Center'

# --- Python 3.11+ -----------------------------------------------------------
function Find-Python {
    $candidates = @(@('py', '-3'), @('python'), @('python3'))
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @($c | Select-Object -Skip 1)
        try {
            $out = & $exe @extra -c "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path $out)) { return $out.Trim() }
        } catch { }
    }
    return $null
}
$Python = Find-Python
if (-not $Python) {
    Write-Host "Python 3.11 or newer was not found." -ForegroundColor Red
    Write-Host "Install it with:  winget install -e --id Python.Python.3.12"
    Write-Host "then open a NEW PowerShell window and run this installer again."
    return
}
Write-Host "==> Using Python at $Python"

# --- download and unpack ----------------------------------------------------
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("gcc-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
    $Archive = Join-Path $Tmp 'gcc.tar.gz'
    if ($env:GCC_ARCHIVE) {
        Write-Host "==> Using local archive $($env:GCC_ARCHIVE)"
        Copy-Item $env:GCC_ARCHIVE $Archive
    } else {
        $Url = "https://github.com/$Repo/releases/download/v$Version/greenhouse-control-center-$Version.tar.gz"
        Write-Host "==> Downloading $Name $Version"
        Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing
    }
    $Unpacked = Join-Path $Tmp 'x'
    New-Item -ItemType Directory -Path $Unpacked | Out-Null
    & tar.exe -xzf $Archive -C $Unpacked
    if ($LASTEXITCODE -ne 0) { throw "tar.exe could not unpack the archive" }
    $Src = Get-ChildItem $Unpacked -Directory | Select-Object -First 1
    if (-not $Src -or -not (Test-Path (Join-Path $Src.FullName 'backend\app'))) { throw "The archive does not look right (backend\app missing)" }

    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $App = Join-Path $Dir 'app'
    if (Test-Path $App) { Remove-Item $App -Recurse -Force }   # the old program files only: data\ and venv\ are kept
    Move-Item $Src.FullName $App
} finally {
    Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# --- Python environment -----------------------------------------------------
$Venv = Join-Path $Dir 'venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    Write-Host "==> Creating the Python environment"
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
}
Write-Host "==> Installing Python packages (a minute or two)"
& $VenvPy -m pip install --disable-pip-version-check --quiet --upgrade pip
& $VenvPy -m pip install --disable-pip-version-check --quiet -r (Join-Path $App 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "pip could not install the requirements" }

# --- settings and launcher ----------------------------------------------------
$Config = Join-Path $Dir 'settings.cmd'
if ($Demo -or $Network -or -not (Test-Path $Config)) {
    $sim = if ($Demo) { 'true' } else { 'false' }
    @(
        'rem Read by start-greenhouse.cmd. GCC_SIMULATE only matters on an EMPTY database (true = simulated demo devices).',
        "set GCC_SIMULATE=$sim",
        'rem 127.0.0.1 = this computer only, 0.0.0.0 = reachable from your network (plain HTTP: private networks only)',
        "set GCC_BIND_HOST=$BindHost"
    ) | Set-Content -Path $Config -Encoding ASCII
}
$Launcher = Join-Path $Dir 'start-greenhouse.cmd'
@(
    '@echo off',
    "title $Name (close this window to stop)",
    'call "%~dp0settings.cmd"',
    'set GCC_DATA_DIR=%~dp0data',
    'cd /d "%~dp0app\backend"',
    'rem open the browser a few seconds after the server starts',
    'start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"',
    '"%~dp0venv\Scripts\python.exe" -m uvicorn app.main:create_app --factory --host %GCC_BIND_HOST% --port 8000',
    'echo.',
    'echo The server stopped (it may already be running in another window: http://127.0.0.1:8000).',
    'pause'
) | Set-Content -Path $Launcher -Encoding ASCII

$Uninstall = Join-Path $Dir 'uninstall.ps1'
@(
    "# Removes $Name and its shortcuts. Your data folder is kept unless you pass -PurgeData.",
    'param([switch]$PurgeData)',
    "`$d = '$Dir'",
    "Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) '$Name.lnk') -ErrorAction SilentlyContinue",
    "Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) '$Name.lnk') -ErrorAction SilentlyContinue",
    'Remove-Item "$d\app", "$d\venv", "$d\start-greenhouse.cmd", "$d\settings.cmd" -Recurse -Force -ErrorAction SilentlyContinue',
    'if ($PurgeData) { Remove-Item $d -Recurse -Force } else { Write-Host "Removed the program. Data kept in $d\data" }'
) | Set-Content -Path $Uninstall -Encoding ASCII

# --- shortcuts --------------------------------------------------------------
function New-Shortcut($Folder) {
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $Folder "$Name.lnk"))
    $lnk.TargetPath = $Launcher
    $lnk.WorkingDirectory = $Dir
    $lnk.WindowStyle = 7   # minimised: the server window stays in the taskbar
    $lnk.Description = "Start $Name and open it in the browser"
    $lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    $lnk.Save()
}
New-Shortcut $Desktop
if ($StartMenu) { New-Shortcut $StartMenu }

Write-Host ""
Write-Host "Done. Double-click the '$Name' shortcut on your Desktop (or in the Start menu)." -ForegroundColor Green
Write-Host "It starts the server and opens http://127.0.0.1:8000 in your browser."
Write-Host "First start: create the administrator with the one-time code in  $Dir\data\setup_code.txt"
Write-Host "Remove it later with:  powershell -File `"$Uninstall`""

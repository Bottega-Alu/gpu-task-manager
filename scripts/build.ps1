# 🛠️ Builds GPU Task Manager: tests, portable app folder, licence notices, installer.
#
#   .\scripts\build.ps1                       # tests + dist\GPUTaskManager\ + Setup.exe
#   .\scripts\build.ps1 -SkipTests            # faster rebuild
#   .\scripts\build.ps1 -NoInstaller          # app folder only (no Inno Setup needed)
#   .\scripts\build.ps1 -CertThumbprint ABC.. # also Authenticode-sign exe and setup
#
# Output:
#   dist\<APP_SLUG>\<APP_SLUG>.exe                 portable app (onedir, no console)
#   installer\Output\<APP_SLUG>-Setup-<ver>.exe    per-user installer, no admin
#   installer\Output\SHA256SUMS.txt
#
# Product name, version, publisher and GUID come only from src\gtm_desktop\brand.py.
# Needs: uv (winget install astral-sh.uv). Installer: Inno Setup 6 (winget install JRSoftware.InnoSetup).

param(
    [switch]$SkipTests,
    [switch]$NoInstaller,
    [string]$CertThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found. Install it with: winget install --id astral-sh.uv --exact, then open a new terminal."
}

# 📦 Environment from the lockfile (Python is fetched by uv if missing)
Step "Environment (uv sync --locked)"
uv sync --locked --group release --group dev
Check "uv sync"

$Brand = uv run --locked python scripts\build_meta.py json | ConvertFrom-Json
Check "brand metadata"
$Slug = $Brand.APP_SLUG
$Version = $Brand.APP_VERSION
Write-Host "$($Brand.APP_NAME) $Version ($Slug)"

# 🧪 Tests
if (-not $SkipTests) {
    Step "Tests"
    uv run --locked python -m pytest -q
    Check "tests"
}

# 🎨 Icon and version resource
Step "Icon and version resource"
$Work = Join-Path $Root "build"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
uv run --locked python scripts\make_icon.py
Check "icon"
$VersionFile = Join-Path $Work "version_info.txt"
uv run --locked python scripts\build_meta.py version-info $VersionFile
Check "version resource"

# 🧊 PyInstaller (onedir: fast start, no temp extraction, friendly to antivirus)
Step "PyInstaller"
$Dist = Join-Path $Root "dist"
if (Test-Path (Join-Path $Dist $Slug)) { Remove-Item -Recurse -Force (Join-Path $Dist $Slug) }
# Pillow's Tk bridge is imported lazily; without these the UI fails with "PyImagingPhoto".
$PillowTk = @("PIL.ImageTk", "PIL._imagingtk", "PIL._tkinter_finder")
$Hidden = @()
foreach ($m in $PillowTk) { $Hidden += @("--hidden-import", $m) }

uv run --locked pyinstaller `
    --noconfirm --clean --windowed --onedir `
    --name $Slug `
    --icon (Join-Path $Root "assets\app.ico") `
    --version-file $VersionFile `
    --paths (Join-Path $Root "src") `
    --distpath $Dist `
    --workpath (Join-Path $Work "pyinstaller") `
    --specpath $Work `
    --add-data "$(Join-Path $Root 'assets\app.ico');assets" `
    --collect-submodules gputaskman `
    --collect-submodules gtm_desktop `
    --exclude-module gputaskman.app `
    --exclude-module textual `
    --exclude-module rich `
    --exclude-module gtm_desktop.demo `
    --exclude-module pytest `
    @Hidden `
    (Join-Path $Root "scripts\entry.py")
Check "PyInstaller"

$AppDir = Join-Path $Dist $Slug
$Exe = Join-Path $AppDir "$Slug.exe"
if (-not (Test-Path $Exe)) { throw "exe not produced: $Exe" }

# 📜 Licence notices
Step "Third-party notices"
uv run --locked python scripts\collect_notices.py $AppDir
Check "notices"
foreach ($f in "README.md", "LICENSE", "NOTICE") { Copy-Item (Join-Path $Root $f) $AppDir -Force }

# ✅ Smoke test: the frozen exe must start and report its version
Step "Smoke test"
$p = Start-Process -FilePath $Exe -ArgumentList "--version" -PassThru -Wait -WindowStyle Hidden
if ($p.ExitCode -ne 0) { throw "frozen exe --version exited with $($p.ExitCode)" }
Write-Host "OK  $Exe"

# ✍️ Optional code signing (strongly recommended for a commercial release: SmartScreen)
function Sign($file) {
    if (-not $CertThumbprint) { return }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)" }
    & $signtool.FullName sign /sha1 $CertThumbprint /fd sha256 /tr $TimestampUrl /td sha256 $file
    Check "signing $file"
}
Sign $Exe

if ($NoInstaller) {
    Write-Host "`nApp folder ready: $AppDir" -ForegroundColor Green
    exit 0
}

# 💿 Installer
Step "Installer (Inno Setup)"
$Iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or use -NoInstaller."
}

$Defines = @(
    "/DAppName=$($Brand.APP_NAME)",
    "/DAppSlug=$Slug",
    "/DAppVersion=$Version",
    "/DAppPublisher=$($Brand.APP_PUBLISHER)",
    "/DAppURL=$($Brand.APP_URL)",
    "/DAppGuid=$($Brand.APP_GUID)",
    "/DAppExeName=$($Brand.EXE_NAME)",
    "/DAppMutex=$($Brand.MUTEX_NAME)",
    "/DRunValue=$($Brand.RUN_VALUE_NAME)",
    "/DSourceDir=$AppDir"
)
& $Iscc @Defines (Join-Path $Root "installer\GPUTaskManager.iss")
Check "ISCC"

$OutDir = Join-Path $Root "installer\Output"
$Setup = Join-Path $OutDir "$Slug-Setup-$Version.exe"
if (-not (Test-Path $Setup)) { throw "installer not produced: $Setup" }
Sign $Setup

$hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $Setup -Leaf)" | Set-Content -Encoding ascii (Join-Path $OutDir "SHA256SUMS.txt")
$mb = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
Write-Host "`nOK  $Setup ($mb MB)" -ForegroundColor Green

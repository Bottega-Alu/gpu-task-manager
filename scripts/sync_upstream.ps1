# 🔄 Replaces src\gputaskman with the latest upstream engine and records the commit in UPSTREAM.md.
#
#   .\scripts\sync_upstream.ps1                 # latest main
#   .\scripts\sync_upstream.ps1 -Ref v0.4.0     # a tag or commit
#
# Review the diff (git diff src/gputaskman) and run the tests before committing.

param([string]$Ref = "main")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("gputaskman-" + [guid]::NewGuid())

git clone --quiet https://github.com/shanselman/gputaskman.git $Tmp
if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
try {
    git -C $Tmp checkout --quiet $Ref
    if ($LASTEXITCODE -ne 0) { throw "unknown ref: $Ref" }
    $commit = (git -C $Tmp rev-parse HEAD).Trim()
    $date = (git -C $Tmp log -1 --format=%cs).Trim()

    $licence = Get-Content (Join-Path $Tmp "LICENSE") -Raw
    if ($licence -notmatch "MIT License") { throw "upstream licence is no longer MIT: stop and review before syncing" }

    $dest = Join-Path $Root "src\gputaskman"
    Remove-Item -Recurse -Force $dest
    Copy-Item -Recurse (Join-Path $Tmp "src\gputaskman") $dest
    Get-ChildItem $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Copy-Item (Join-Path $Tmp "LICENSE") (Join-Path $Root "licenses\gputaskman-LICENSE.txt") -Force

    $up = Join-Path $Root "UPSTREAM.md"
    $text = Get-Content $up -Raw
    $text = $text -replace '- Commit: `[0-9a-f]+`', "- Commit: ``$commit``"
    $text = $text -replace '- Date: \S+', "- Date: $date"
    Set-Content -Path $up -Value $text -NoNewline -Encoding utf8
    Write-Host "Synced to $commit ($date). Now: uv run python -m pytest -q" -ForegroundColor Green
} finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}

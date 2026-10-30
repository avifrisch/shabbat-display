# Builds dist\ShabbatDisplay.zip, the download for another PC in the house.
# Upload it to your website; on the other PC, download it, extract it, and
# double-click setup-windows.bat. Setup finds the always-on display PC by itself.
#
# Only committed files go in (git archive), so settings.json, its calendar links and
# NYT cookie, the logs and the cache never do. Developer files are left out
# (export-ignore in .gitattributes).

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
if (git status --porcelain --untracked-files=no) {
    Write-Host 'Note: there are uncommitted changes; the zip has only what is committed.' -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force 'dist' | Out-Null
$zip = Join-Path $Here 'dist\ShabbatDisplay.zip'
git archive --format=zip --prefix=ShabbatDisplay/ -o $zip HEAD
$kb = [math]::Round((Get-Item $zip).Length / 1KB)
Write-Host "Built $zip ($kb KB, from commit $(git rev-parse --short HEAD))." -ForegroundColor Green
Write-Host 'Upload it to your website. On the other PC: download, extract, double-click setup-windows.bat.'

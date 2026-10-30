# Sets up the AI usage reporter on Windows. The editor (Settings › AI usage) gives the line to run in PowerShell:
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/bek00letz/epaper-panel/<ref>/reporter/install.ps1))) `
#     -Ref <ref> -Address <add-on address> -Code <code>
#
# It fetches the reporter at that release of the add-on, copies it to its own folder in
# %LOCALAPPDATA%, and runs its setup.
param([string]$Ref = "main", [Parameter(Mandatory = $true)][string]$Address, [Parameter(Mandatory = $true)][string]$Code)
$ErrorActionPreference = "Stop"
$Repo = "bek00letz/epaper-panel"
$HomeDir = Join-Path $env:LOCALAPPDATA "e-Paper Usage Reporter"
$App = Join-Path $HomeDir "app"

# The real Python, not the Microsoft Store's stand-in: the py launcher first.
$Probe = "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')"
$Python = $null
foreach ($try in @({ py -3 -c $Probe }, { python -c $Probe })) {
  try {
    $exe = & $try 2>$null
    if ($LASTEXITCODE -eq 0 -and $exe) { $Python = "$exe".Trim(); break }
  } catch { }
}
if (-not $Python) {
  Write-Host "The reporter needs Python 3.9 or later. Install it from python.org, then run this again."
  return
}

$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("epaper-usage-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Tmp | Out-Null
try {
  $Zip = Join-Path $Tmp "reporter.zip"
  try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/$Ref.zip" -OutFile $Zip }
  catch { Write-Host "Couldn't download the reporter ($Ref). Check this computer's internet connection and try again."; return }
  Expand-Archive -Path $Zip -DestinationPath $Tmp
  $From = Get-ChildItem -Path $Tmp -Directory | ForEach-Object { Join-Path $_.FullName "reporter" } | Where-Object { Test-Path (Join-Path $_ "run.py") } | Select-Object -First 1
  if (-not $From) { Write-Host "The reporter wasn't where it should be. Copy the command from the editor again."; return }
  New-Item -ItemType Directory -Force -Path $App | Out-Null
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $App "epaper_usage")
  Copy-Item -Recurse (Join-Path $From "epaper_usage") $App
  Copy-Item (Join-Path $From "run.py") $App
  & $Python (Join-Path $App "run.py") setup --address $Address --code $Code
} finally {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp
}

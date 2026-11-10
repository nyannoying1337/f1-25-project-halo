# Tests, builds and packs the addon zip for the Swofty launcher, then installs it into the launcher's addon store.
#   .\package.ps1             test, build, pack, install (the install is skipped while F1_25.exe is running)
#   .\package.ps1 -NoInstall  test, build and pack only
#   .\package.ps1 -Swofty <path to swofty.exe>   the launcher's CLI, when it is not on PATH
# The archives in erp\ are built from the game's own UI archives, so they are not in the repository:
# take them from a release zip or rebuild them (README.md, Build).
param([switch]$NoInstall, [string]$Swofty = "swofty")
$ErrorActionPreference = "Stop"
$manifest = Get-Content "$PSScriptRoot\swofty.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$ver = $manifest.version

# An older launcher refused to start on a manifest string over 255 bytes.
$long = [regex]::Matches((Get-Content "$PSScriptRoot\swofty.json" -Raw -Encoding UTF8), '"(?:[^"\\]|\\.)*"') |
    Where-Object { [Text.Encoding]::UTF8.GetByteCount($_.Value) - 2 -gt 255 }
if ($long) { throw "swofty.json has a string over 255 bytes: $($long[0].Value.Substring(0, 70))..." }

$erps = "halo_scene.erp", "halo_template.erp", "halo_spectator.erp", "tower_scene.erp", "tower_template.erp",
    "tower_replay.erp", "tower_replay_scene.erp", "tower_spectator.erp"
$missing = @($erps | Where-Object { -not (Test-Path "$PSScriptRoot\erp\$_") })
if ($missing) { throw "erp\$($missing[0]) is missing: take the erp folder from a release zip or rebuild it (README.md, Build)" }

& cmd /c "`"$PSScriptRoot\native\build.cmd`""
if ($LASTEXITCODE -ne 0) { throw "tests or build failed ($LASTEXITCODE), nothing packed or installed" }

$stage = Join-Path ([IO.Path]::GetTempPath()) "project-halo-stage"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stage
New-Item -ItemType Directory -Force "$stage\native", "$stage\erp", "$stage\icons" | Out-Null
Copy-Item "$PSScriptRoot\swofty.json", "$PSScriptRoot\README.md", "$PSScriptRoot\LICENSE" $stage
Copy-Item "$PSScriptRoot\icons\halo.png" "$stage\icons"
Copy-Item "$PSScriptRoot\erp\halo.json" "$stage\erp"
foreach ($e in $erps) { Copy-Item "$PSScriptRoot\erp\$e" "$stage\erp" }
Copy-Item "$PSScriptRoot\native\halo_hud.dll" "$stage\native"

# swofty.json at the zip root and forward slashes, as the Swofty addon registry expects.
$out = Join-Path $PSScriptRoot "dist\project-halo-$ver.zip"
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
Remove-Item -ErrorAction SilentlyContinue $out
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open($out, "Create")
try {
    Get-ChildItem -Recurse -File $stage | ForEach-Object {
        $rel = $_.FullName.Substring($stage.Length).TrimStart('\').Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $rel) | Out-Null
    }
} finally { $zip.Dispose() }
Write-Host "packed $out"

if ($NoInstall) {
    Write-Host "packed only, nothing installed"
} elseif (Get-Process -Name F1_25 -ErrorAction SilentlyContinue) {
    Write-Warning "F1_25.exe is running: packed, NOT installed. Close the game and run package.ps1 again."
} else {
    & $Swofty addons install $stage
    if ($LASTEXITCODE -ne 0) { throw "install failed ($LASTEXITCODE)" }
}

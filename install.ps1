# Install the released application for the current Windows user.
$ErrorActionPreference = 'Stop'
$version = '0.4.15'
$package = $env:POKESIM_INSTALL_PACKAGE
if (-not $package) {
    $package = "https://github.com/afk-sapien/PokeSim/releases/download/v$version/pokesim-$version-py3-none-any.whl"
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvBin = Join-Path $HOME '.local\bin\uv.exe'
if ($uvCommand) {
    $uvBin = $uvCommand.Source
} elseif (-not (Test-Path $uvBin)) {
    Write-Host 'Installing uv for your user account...'
    $installer = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName() + '.ps1')
    $previousInstallDir = $env:UV_INSTALL_DIR
    $previousNoModifyPath = $env:UV_NO_MODIFY_PATH
    try {
        Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/install.ps1' -OutFile $installer
        $env:UV_INSTALL_DIR = Join-Path $HOME '.local\bin'
        $env:UV_NO_MODIFY_PATH = '1'
        & powershell -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw 'uv installation failed. Check your connection and retry.' }
    } finally {
        $env:UV_INSTALL_DIR = $previousInstallDir
        $env:UV_NO_MODIFY_PATH = $previousNoModifyPath
        Remove-Item $installer -ErrorAction SilentlyContinue
    }
}

Write-Host 'Installing PokeSim with managed Python 3.12. No Git or system Python is needed.'
& $uvBin tool install --python 3.12 --managed-python --upgrade $package
if ($LASTEXITCODE -ne 0) { throw 'PokeSim installation failed. Check the error above, then retry.' }
$binDir = & $uvBin tool dir --bin
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the installed commands.' }
$launcher = Join-Path $binDir 'pokesim-desktop.exe'
& $launcher --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The installed launcher failed. Please include the error in a bug report.' }
Write-Host "`nPokeSim is installed. Start it with:"
Write-Host "  & `"$launcher`""
Write-Host "`nYour browser will open the Library. Add your own Red or Blue ROM there."
Write-Host 'For the short pokesim-desktop command, add the tool directory to PATH with:'
Write-Host "  & `"$uvBin`" tool update-shell"
Write-Host 'Then open a new terminal. Save and quit PokeSim before rerunning this installer to update.'

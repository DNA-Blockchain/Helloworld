# RabbitSoftware.inc installer for Windows (PowerShell 5.1 or 7).
#
# One line, in an ordinary PowerShell window (no admin needed):
#
#     irm https://raw.githubusercontent.com/DNA-Blockchain/Helloworld/master/install.ps1 | iex
#
# It downloads the latest RabbitSoftware release from GitHub into %LOCALAPPDATA%\RabbitSoftware, gives it its own Python
# environment, and adds a `rabbit` command:  rabbit chat | rabbit web | rabbit ask "..."
# Running it again updates the code and keeps your data (chains, notes, research, settings).
#
# It never installs anything else on its own: if Python or Ollama is missing it says so and gives the
# command to run. Options, as environment variables set before running it:
#   RABBIT_HOME       where to install (default %LOCALAPPDATA%\RabbitSoftware)
#   RABBIT_SOURCE     a .zip of the project to install from instead of GitHub
#   RABBIT_CHANNEL    "dev" installs the newest code (master) instead of the latest release
#   RABBIT_DRY_RUN    any value: say what would be installed, and stop
#   RABBIT_MODEL_URL  a model server to use (https); RabbitSoftware.inc asks before each question sent there

function Install-RabbitSoftware {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"          # Invoke-WebRequest is far slower with the progress bar
    $repo = "DNA-Blockchain/Helloworld"
    $repoZip = "https://github.com/$repo/archive/refs/heads/master.zip"
    $label = "the development version (master)"
    $home_ = if ($env:RABBIT_HOME) { $env:RABBIT_HOME } else { Join-Path $env:LOCALAPPDATA "RabbitSoftware" }

    Write-Host "RabbitSoftware.inc installer" -ForegroundColor Cyan

    # Which version: the latest release, unless RABBIT_CHANNEL=dev (master) or a zip was given.
    if (-not $env:RABBIT_SOURCE -and $env:RABBIT_CHANNEL -ne "dev") {
        try {
            $release = Invoke-RestMethod -UseBasicParsing -Headers @{ "User-Agent" = "RabbitSoftware-installer" } `
                -Uri "https://api.github.com/repos/$repo/releases/latest"
            $repoZip = "https://github.com/$repo/archive/refs/tags/$($release.tag_name).zip"
            $label = "release $($release.tag_name)"
        } catch {
            Write-Host "No release is published yet, so this installs the development version."
        }
    }
    if ($env:RABBIT_SOURCE) { $label = "the zip in RABBIT_SOURCE" }
    Write-Host "Installing $label."
    if ($env:RABBIT_DRY_RUN) {
        Write-Host "Dry run: would download $repoZip into $home_"
        return
    }

    # 1. Python 3.11 or newer (the py launcher first; the Microsoft Store "python" stub doesn't count)
    $python = $null
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args_ = @($candidate | Select-Object -Skip 1)
        $version = & $exe.Source @args_ -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -and [version]$version -ge [version]"3.11") {
            $python = @($exe.Source) + $args_
            break
        }
    }
    if (-not $python) {
        Write-Host "Python 3.11 or newer is needed and wasn't found. Install it with:" -ForegroundColor Yellow
        Write-Host "    winget install -e --id Python.Python.3.12"
        Write-Host "then open a new PowerShell window and run this installer again."
        return
    }
    Write-Host "Using Python $version."

    # 2. The project code (downloaded, or the zip given in RABBIT_SOURCE)
    $work = Join-Path ([IO.Path]::GetTempPath()) ("rabbit-install-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $work | Out-Null
    try {
        $zip = Join-Path $work "project.zip"
        if ($env:RABBIT_SOURCE) {
            Copy-Item $env:RABBIT_SOURCE $zip
        } else {
            Write-Host "Downloading the project from GitHub..."
            Invoke-WebRequest -UseBasicParsing -Uri $repoZip -OutFile $zip
        }
        Expand-Archive -Path $zip -DestinationPath (Join-Path $work "x") -Force
        $top = Get-ChildItem (Join-Path $work "x") -Directory | Select-Object -First 1
        if (-not $top -or -not (Test-Path (Join-Path $top.FullName "rabbit.py"))) {
            throw "the download doesn't look like the RabbitSoftware project (no rabbit.py)"
        }
        New-Item -ItemType Directory -Force $home_ | Out-Null
        # Copying over an existing install updates the code; data folders aren't in the download, so they stay.
        Copy-Item -Path (Join-Path $top.FullName "*") -Destination $home_ -Recurse -Force
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
    Write-Host "Installed the code in $home_"

    # 3. Its own Python environment, so nothing else on this PC is changed
    $venvPython = Join-Path $home_ ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating a Python environment..."
        $pyArgs = @($python | Select-Object -Skip 1) + @("-m", "venv", (Join-Path $home_ ".venv"))
        & $python[0] @pyArgs
        if ($LASTEXITCODE -ne 0) { throw "creating the Python environment failed" }
    }
    Write-Host "Installing the Python packages (a few minutes the first time)..."
    & $venvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
    & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $home_ "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "installing the Python packages failed; see the messages above" }

    # 4. The `rabbit` command, on this user's PATH
    $bin = Join-Path $home_ "bin"
    New-Item -ItemType Directory -Force $bin | Out-Null
    Set-Content -Path (Join-Path $bin "rabbit.cmd") -Encoding ASCII -Value @(
        "@echo off",
        "`"%~dp0..\.venv\Scripts\python.exe`" `"%~dp0..\rabbit.py`" %*"
    )
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (($userPath -split ";") -contains $bin)) {
        [Environment]::SetEnvironmentVariable("Path", (@($userPath, $bin) | Where-Object { $_ }) -join ";", "User")
    }
    if (-not (($env:Path -split ";") -contains $bin)) { $env:Path = "$env:Path;$bin" }

    # 5. The model server, if one was given
    if ($env:RABBIT_MODEL_URL) {
        & $venvPython (Join-Path $home_ "rabbit.py") model-server $env:RABBIT_MODEL_URL
    }

    # 6. Tell (never install) what's optional
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "Optional: to answer with a model on this PC (and search by meaning), install Ollama:" -ForegroundColor Yellow
        Write-Host "    winget install -e --id Ollama.Ollama"
    }

    Write-Host ""
    Write-Host "Done. Type one of these (in any new PowerShell window too):" -ForegroundColor Green
    Write-Host "    rabbit chat     talk in this window"
    Write-Host "    rabbit web      talk in a web page on this PC"
}

try {
    Install-RabbitSoftware
} catch {
    Write-Host "Install stopped: $($_.Exception.Message)" -ForegroundColor Red
}

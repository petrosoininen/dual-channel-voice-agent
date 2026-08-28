[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$sourceRoot = (Split-Path -Parent $PSScriptRoot)
$tempBase = Join-Path $sourceRoot "release-scan"
$tempParent = Join-Path $tempBase ("portable-" + [guid]::NewGuid().ToString("N"))
$copyRoot = Join-Path $tempParent "dual-channel-voice-agent-pattern"
$pythonProcess = $null
$viteProcess = $null

function Assert-ApprovedNetworkUri {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -eq "null") {
        return
    }
    $uri = $null
    if (-not [Uri]::TryCreate($Value, [UriKind]::Absolute, [ref]$uri)) {
        throw "Inherited $Name is not an absolute URI."
    }
    $hostName = $uri.Host.ToLowerInvariant()
    if (
        $hostName -ne "localhost" -and
        $hostName -ne "127.0.0.1" -and
        $hostName -notmatch "(^|\.)microsoft\.com$" -and
        $hostName -notmatch "(^|\.)microsoft\.io$" -and
        $hostName -notmatch "(^|\.)azure\.com$"
    ) {
        throw "Inherited $Name is outside the approved package/local proxy boundary."
    }
}

function Assert-PortableProxyBoundary {
    $proxyVariables = @(
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NPM_CONFIG_PROXY",
        "NPM_CONFIG_HTTPS_PROXY",
        "PIP_INDEX_URL"
    )
    foreach ($name in $proxyVariables) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        Assert-ApprovedNetworkUri -Name $name -Value $value
    }
}

function Invoke-WithSafeRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        & $Action
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -eq 1) {
            Write-Warning "$Name failed; retrying once with the same locked inputs and inherited network settings."
            Start-Sleep -Seconds 2
        }
    }
    throw "$Name failed after one safe retry."
}

function Wait-ForLocalUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name
    )
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "$Name did not become ready on loopback."
}

Assert-PortableProxyBoundary
New-Item -ItemType Directory -Path $tempBase -Force | Out-Null
if (
    -not $tempParent.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or
    -not ([IO.Path]::GetFileName($tempParent)).StartsWith("portable-")
) {
    throw "Portable-copy temporary path failed the cleanup safety check."
}

try {
    $sourceReparsePoints = Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
    if ($sourceReparsePoints.Count -gt 0) {
        throw "Portable source contains a reparse point and cannot be copied safely."
    }
    New-Item -ItemType Directory -Path $copyRoot | Out-Null
    $manifestPath = Join-Path $sourceRoot "release-manifest.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($relative in $manifest.files) {
        $source = [IO.Path]::GetFullPath((Join-Path $sourceRoot $relative))
        if (-not $source.StartsWith($sourceRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Portable manifest contains an escaping path."
        }
        $destination = Join-Path $copyRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force |
            Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    if (Test-Path -LiteralPath (Join-Path $copyRoot ".env")) {
        throw "Portable copy retained ignored local configuration."
    }

    foreach ($requirementsFile in @("requirements.txt", "requirements-dev.txt")) {
        $requirements = Get-Content (Join-Path $copyRoot $requirementsFile) |
            Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") }
        foreach ($requirement in $requirements) {
            if ($requirement -match "^-r\s+(?<path>[A-Za-z0-9_.-]+)$") {
                if (-not (Test-Path (Join-Path $copyRoot $Matches["path"]))) {
                    throw "Portable Python requirements include a missing manifest."
                }
            }
            elseif ($requirement -notmatch "^[A-Za-z0-9_.-]+==[^=\s]+$") {
                throw "Portable Python installation requires exact requirement pins."
            }
        }
    }
    if (-not (Test-Path (Join-Path $copyRoot "package-lock.json"))) {
        throw "Portable npm installation requires package-lock.json."
    }
    if (-not (Test-Path (Join-Path $copyRoot "pyproject.toml"))) {
        throw "Portable Python installation requires pyproject.toml."
    }

    Set-Location $copyRoot
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Portable validation requires Python 3.11 or later."
    }
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Portable virtual environment creation failed."
    }
    $python = Join-Path $copyRoot ".venv\Scripts\python.exe"
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $pipIndex = (& $python -m pip config get --global global.index-url)
    if ($LASTEXITCODE -ne 0) {
        throw "Portable install requires an inherited pip index."
    }
    Assert-ApprovedNetworkUri -Name "pip global.index-url" -Value $pipIndex
    $npmRegistry = (& $npm config get registry)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the inherited npm registry."
    }
    Assert-ApprovedNetworkUri -Name "npm registry" -Value $npmRegistry
    foreach ($npmProxyName in @("proxy", "https-proxy")) {
        $npmProxy = (& $npm config get $npmProxyName)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect inherited npm $npmProxyName configuration."
        }
        Assert-ApprovedNetworkUri -Name "npm $npmProxyName" -Value $npmProxy
    }
    Invoke-WithSafeRetry "Pinned Python install" {
        & $python -m pip install --disable-pip-version-check --no-input -r requirements-dev.txt
    }
    Invoke-WithSafeRetry "Locked npm install" {
        & $npm ci --no-audit --no-fund
    }

    & $python -m pytest -q tests\backend tests\contract tests\repository
    if ($LASTEXITCODE -ne 0) { throw "Portable Python tests failed." }
    & $npm run test:frontend
    if ($LASTEXITCODE -ne 0) { throw "Portable frontend tests failed." }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw "Portable frontend build failed." }
    & $python -m scripts.verify_contract_freeze
    if ($LASTEXITCODE -ne 0) { throw "Portable contract freeze verification failed." }
    & $python -m scripts.generate_contract_schemas --check
    if ($LASTEXITCODE -ne 0) { throw "Portable schema generation drift check failed." }

    $pythonProcess = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8120"
    ) -WorkingDirectory $copyRoot -PassThru
    Wait-ForLocalUrl "http://127.0.0.1:8120/api/health" "Portable API"
    $capabilities = Invoke-RestMethod -Uri "http://127.0.0.1:8120/api/capabilities"
    if (
        $capabilities.agentProvider -ne "deterministic" -or
        $capabilities.voiceProvider -ne "off" -or
        $capabilities.statePersistence -ne "process-memory-only"
    ) {
        throw "Portable API capability smoke returned an unexpected contract."
    }

    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $vite = Join-Path $copyRoot "node_modules\vite\bin\vite.js"
    $viteProcess = Start-Process -FilePath $node -ArgumentList @(
        $vite, "--host", "127.0.0.1", "--port", "15175"
    ) -WorkingDirectory $copyRoot -PassThru
    Wait-ForLocalUrl "http://127.0.0.1:15175/" "Portable UI"
    Write-Output "Portable copy install, tests, build, API smoke, and UI asset smoke passed."
}
finally {
    foreach ($process in @($viteProcess, $pythonProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
    }
    Set-Location $sourceRoot
    if (Test-Path -LiteralPath $tempParent) {
        if (
            $tempParent.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
            ([IO.Path]::GetFileName($tempParent)).StartsWith("portable-")
        ) {
            Remove-Item -LiteralPath $tempParent -Recurse -Force
        }
        else {
            throw "Refusing to clean an unexpected portable-copy path."
        }
        if (
            (Test-Path -LiteralPath $tempBase) -and
            -not (Get-ChildItem -LiteralPath $tempBase -Force)
        ) {
            Remove-Item -LiteralPath $tempBase -Force
        }
    }
}

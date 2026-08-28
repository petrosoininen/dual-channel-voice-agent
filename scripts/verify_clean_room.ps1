[CmdletBinding()]
param(
    [string]$ProhibitedTermsPath = $env:DUAL_CHANNEL_PROHIBITED_TERMS_FILE
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$excludedDirectories = @(
    ".git",
    ".venv",
    ".terraform",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "test-results",
    "playwright-report",
    "coverage",
    "infra-validation",
    "release-scan"
)
$textExtensions = @(
    ".bicep",
    ".cfg",
    ".css",
    ".example",
    ".hcl",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".tf",
    ".tfvars",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml"
)
$extensionlessText = @(
    "AGENTS.md",
    "CLAUDE.md",
    "Dockerfile",
    "LICENSE"
)
$patterns = [ordered]@{
    "private key" = "-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    "bearer value" = "(?i)\bbearer\s+[a-z0-9._~-]{16,}"
    "Azure resource identifier" = "(?i)/subscriptions/[0-9a-f-]{8,}"
    "connection secret" = "(?i)(?:AccountKey|SharedAccessSignature)\s*="
    "assigned secret" = "(?i)(?:AZURE_CLIENT_SECRET|API_KEY|ACCESS_TOKEN)\s*=\s*(?!<)[^\s#]+"
    "absolute personal path" = "(?i)\b[A-Z]:\\Users\\"
    "home-directory path" = "(?i)/(?:home|Users)/[A-Za-z0-9._-]+/"
    "configured Azure endpoint" = "(?i)https://[a-z0-9][a-z0-9.-]*\.(?:services\.ai|cognitiveservices|openai)\.azure\.com"
    "internal package feed" = "(?i)https://[^/\s]*(?:pkgs\.visualstudio\.com|pkgs\.dev\.azure\.com)/"
    "SSH repository reference" = "(?i)\bgit@[^:\s]+:"
}
$companyNamePattern = "\bMicro" + "soft\b"
$allowedCompanyTechnicalPattern = "Micro" + "soft\.(?:Authorization|CognitiveServices|DefaultV2|Resources)\b"

function Get-RelativePath([System.IO.FileSystemInfo]$Item) {
    return [IO.Path]::GetRelativePath($root, $Item.FullName).Replace("\", "/")
}

function Test-IsExcluded([string]$Relative) {
    $segments = $Relative -split "[\\/]"
    foreach ($directory in $excludedDirectories) {
        if ($segments -contains $directory) {
            return $true
        }
    }
    return $false
}

$findings = [System.Collections.Generic.List[string]]::new()
$reparsePoints = Get-ChildItem -Path $root -Recurse -Force | Where-Object {
    -not (Test-IsExcluded (Get-RelativePath $_)) -and
    ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
}
foreach ($reparsePoint in $reparsePoints) {
    $findings.Add("reparse point is not portable: $(Get-RelativePath $reparsePoint)")
}

$files = Get-ChildItem -Path $root -Recurse -File -Force | Where-Object {
    $relative = Get-RelativePath $_
    -not (Test-IsExcluded $relative) -and (
        $textExtensions -contains $_.Extension -or
        $extensionlessText -contains $_.Name
    )
}

foreach ($file in $files) {
    $relative = Get-RelativePath $file
    $content = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($entry in $patterns.GetEnumerator()) {
        if ($content -match $entry.Value) {
            $findings.Add("$($entry.Key): $relative")
        }
    }
    $companyCandidate = $content -creplace $allowedCompanyTechnicalPattern, ""
    if ($companyCandidate -cmatch $companyNamePattern) {
        $findings.Add("prohibited company prose: $relative")
    }
    if (
        $content -match "(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b" -and
        $relative -notmatch "^(?:contracts/fixtures|fixtures|tests)/"
    ) {
        $findings.Add("non-fixture GUID: $relative")
    }
}

if ($ProhibitedTermsPath) {
    $resolvedTerms = Resolve-Path -LiteralPath $ProhibitedTermsPath
    if ($resolvedTerms.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The prohibited-terms file must stay outside the publishable asset."
    }
    $terms = Get-Content -LiteralPath $resolvedTerms.Path | Where-Object {
        $_.Trim() -and -not $_.TrimStart().StartsWith("#")
    }
    foreach ($file in $files) {
        $content = Get-Content -LiteralPath $file.FullName -Raw
        if ($null -eq $content) {
            $content = ""
        }
        foreach ($term in $terms) {
            if ($content.IndexOf($term.Trim(), [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $findings.Add("prohibited external term: $(Get-RelativePath $file)")
            }
        }
    }
}

$moduleFiles = $files | Where-Object {
    $_.Extension -in @(".js", ".mjs", ".ts", ".tsx")
}
foreach ($file in $moduleFiles) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    $matches = [regex]::Matches(
        $content,
        "(?m)(?:from\s+|import\s*)['""](?<path>\.{1,2}/[^'""]+)['""]"
    )
    foreach ($match in $matches) {
        $resolved = [IO.Path]::GetFullPath(
            (Join-Path $file.DirectoryName $match.Groups["path"].Value)
        )
        $relativeResolved = [IO.Path]::GetRelativePath($root, $resolved)
        if ($relativeResolved -eq ".." -or $relativeResolved.StartsWith("..$([IO.Path]::DirectorySeparatorChar)")) {
            $findings.Add("relative import escapes project root: $(Get-RelativePath $file)")
        }
    }
}

foreach ($file in ($files | Where-Object { $_.Extension -eq ".py" })) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    if (
        $content -match "(?m)^\s*(?:from\s+main\b|import\s+main\b)" -or
        $content -match "\bsys\.path\b"
    ) {
        $findings.Add("root import or path injection: $(Get-RelativePath $file)")
    }
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    throw "Clean-room and sensitive-reference scan failed."
}

Write-Output "Clean-room and sensitive-reference scan passed."

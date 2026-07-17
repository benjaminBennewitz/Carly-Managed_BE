param(
  [string]$Root = ".",
  [int]$Depth = 8,
  [switch]$Files,
  [switch]$Ascii,
  [string[]]$ExcludeDirs = @(".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "staticfiles", "node_modules", "dist", "build", ".tox"),
  [string[]]$CollapseDirs = @("migrations"),
  [string[]]$ExcludeFiles = @("*.pyc", "*.pyo", "*.pyd", ".DS_Store"),
  [string]$OutFile = "",
  [switch]$ToClipboard
)

$lines = New-Object System.Collections.Generic.List[string]

if ($Ascii.IsPresent) {
  $TEE   = "|-- "
  $ELBOW = "\-- "
  $P_V   = "|   "
  $P_S   = "    "
} else {
  $CHR_T = [char]0x251C
  $CHR_L = [char]0x2514
  $CHR_V = [char]0x2502
  $CHR_H = [char]0x2500
  $TEE   = "$CHR_T$CHR_H$CHR_H "
  $ELBOW = "$CHR_L$CHR_H$CHR_H "
  $P_V   = "$CHR_V   "
  $P_S   = "    "
}

function Test-IncludedFile {
  param([string]$Name)
  if (-not $Files.IsPresent) { return $false }
  foreach ($pat in $ExcludeFiles) {
    if ($Name -like $pat) { return $false }
  }
  return $true
}

function Add-TreeLines {
  param(
    [string]$Path,
    [string]$Prefix = "",
    [int]$Level = 0
  )

  if ($Level -ge $Depth) { return }

  $items = Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue |
    Where-Object {
      if ($_.PSIsContainer) {
        $ExcludeDirs -notcontains $_.Name
      } else {
        Test-IncludedFile -Name $_.Name
      }
    } |
    Sort-Object @{ Expression = { $_.PSIsContainer }; Descending = $true }, Name

  for ($i = 0; $i -lt $items.Count; $i++) {
    $item = $items[$i]
    $isLast = ($i -eq ($items.Count - 1))

    $branch = if ($isLast) { $ELBOW } else { $TEE }
    $displayName = if ($item.PSIsContainer) { "$($item.Name)/" } else { $item.Name }

    $lines.Add("$Prefix$branch$displayName")

    if ($item.PSIsContainer) {
      $nextPrefix = if ($isLast) { $Prefix + $P_S } else { $Prefix + $P_V }

      if ($CollapseDirs -contains $item.Name) {
        $lines.Add("$nextPrefix$ELBOW...")
      } else {
        Add-TreeLines -Path $item.FullName -Prefix $nextPrefix -Level ($Level + 1)
      }
    }
  }
}

$resolved = (Resolve-Path -LiteralPath $Root).Path
$rootName = Split-Path $resolved -Leaf

$lines.Add("$rootName/")
Add-TreeLines -Path $resolved -Prefix "" -Level 0

$text = ($lines -join "`r`n")

if ($ToClipboard.IsPresent) {
  Set-Clipboard -Value $text
  return
}

if ($OutFile -and $OutFile.Trim().Length -gt 0) {
  $target = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path (Get-Location) $OutFile }
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($target, $text, $utf8NoBom)
  return
}

$text
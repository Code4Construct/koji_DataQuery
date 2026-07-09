param(
    [string]$ZipPath = "dist/koji_DataQuery.zip",
    [string]$PluginName = "koji_DataQuery"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

if (-not (Test-Path $ZipPath)) {
    throw "Plugin ZIP was not generated: $ZipPath"
}

$resolvedZip = (Resolve-Path $ZipPath).Path
$archive = [IO.Compression.ZipFile]::OpenRead($resolvedZip)
try {
    $entries = $archive.Entries.FullName
}
finally {
    $archive.Dispose()
}

$backslashEntries = $entries | Where-Object { $_ -match "\\" }
if ($backslashEntries) {
    throw "ZIP contains backslashes in entry names, which QGIS plugin upload rejects: $($backslashEntries -join ', ')"
}

$unexpectedTopLevel = $entries | Where-Object {
    $_ -and -not $_.StartsWith("$PluginName/")
}
if ($unexpectedTopLevel) {
    throw "ZIP contains entries outside $PluginName/: $($unexpectedTopLevel -join ', ')"
}

$required = @(
    "$PluginName/metadata.txt",
    "$PluginName/__init__.py",
    "$PluginName/koji_DataQuery.py",
    "$PluginName/icon.png"
)

foreach ($entry in $required) {
    if ($entries -notcontains $entry) {
        throw "Required ZIP entry was not found: $entry"
    }
}

$blocked = $entries | Where-Object {
    $_ -match '(^|/)__pycache__/' -or
    $_ -match '\.py[co]$' -or
    $_ -match '(^|/)\.git/' -or
    $_ -match '(^|/)\.github/' -or
    $_ -match '(^|/)tools/' -or
    $_ -match '(^|/)dist/' -or
    $_ -match 'ChatGPT Image'
}
if ($blocked) {
    throw "ZIP contains files that should not be distributed: $($blocked -join ', ')"
}

$metadataEntry = $entries | Where-Object { $_ -eq "$PluginName/metadata.txt" }
if (-not $metadataEntry) {
    throw "metadata.txt is missing."
}

Get-Item $resolvedZip | Select-Object FullName, Length, LastWriteTime
Write-Host "Validated $resolvedZip"


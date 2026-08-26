<#
.SYNOPSIS
  Read a card back and sha256-compare it to an image, WITHOUT rewriting (read-only).
.DESCRIPTION
  Companion to Restore-Card.ps1. Opens \\.\PHYSICALDRIVE<n> read-only and hashes the
  first <image-size> bytes, comparing to the image's sha256. On a read error it logs the
  exact byte offset and retries that block a few times — so a transient SD-controller
  hiccup (common right after a big write) is distinguished from a real bad sector, and
  two runs can be compared by offset. Read-only: it never writes the card.
.EXAMPLE
  .\Verify-Card.ps1 -DiskNumber 2 -ImageFile C:\Users\me\sdcard\sd-card.img
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][int]$DiskNumber,
  [Parameter(Mandatory)][string]$ImageFile,
  [string]$LogFile
)
$ErrorActionPreference = 'Stop'
if (-not $LogFile) { $LogFile = [IO.Path]::ChangeExtension($ImageFile, $null).TrimEnd('.') + '-verify.log' }
function Log([string]$m) {
  $line = ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $m)
  Write-Host $line; Add-Content -Path $LogFile -Value $line -Encoding utf8
}
Set-Content -Path $LogFile -Value ('verify started {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Log ("elevated: {0}" -f $isAdmin)
if (-not $isAdmin) { Log 'ERROR: not elevated - raw disk read needs Administrator.'; exit 2 }
if (-not (Test-Path $ImageFile)) { Log ("ERROR: image not found: {0}" -f $ImageFile); exit 5 }
$imgSize = [int64](Get-Item $ImageFile).Length
$disk = Get-Disk -Number $DiskNumber
Log ("target : disk {0}  {1}GB  bus={2}  '{3}'" -f $disk.Number,[math]::Round($disk.Size/1GB,2),$disk.BusType,$disk.FriendlyName)
Log ("image  : {0}  ({1:n0} bytes)" -f $ImageFile, $imgSize)
if ($disk.IsSystem -or $disk.IsBoot) { Log 'REFUSING: target is the system/boot disk.'; exit 3 }

Add-Type -Namespace Win32 -Name RawR -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
public static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFileW(
  string lpFileName, uint dwDesiredAccess, uint dwShareMode, System.IntPtr lpSecurityAttributes,
  uint dwCreationDisposition, uint dwFlagsAndAttributes, System.IntPtr hTemplateFile);
'@
$GENERIC_READ = [uint32]2147483648
$FILE_SHARE   = [uint32]3          # read|write
$OPEN_EXISTING= [uint32]3
$path = '\\.\PHYSICALDRIVE{0}' -f $DiskNumber

# lock+dismount lettered volumes so nothing else touches the device mid-read
$vols = Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue | Where-Object DriveLetter
foreach ($v in $vols) {
  try { $null = & mountvol ("{0}:" -f $v.DriveLetter) /p 2>$null } catch {}
}

$imgHash = (Get-FileHash -Path $ImageFile -Algorithm SHA256).Hash.ToLower()
$h = [Win32.RawR]::CreateFileW($path, $GENERIC_READ, $FILE_SHARE, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
if ($h.IsInvalid) { Log ("ERROR: CreateFile failed ({0})" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error()); exit 7 }
$fs  = New-Object System.IO.FileStream($h, [System.IO.FileAccess]::Read, 8MB)
$sha = [System.Security.Cryptography.SHA256]::Create()
$buf = New-Object byte[] (8MB)
$done = [int64]0
$badOffsets = @()
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$nextReport = 4GB
try {
  while ($done -lt $imgSize) {
    $want = [int][math]::Min([int64]$buf.Length, [int64]($imgSize - $done))
    $n = 0; $ok = $false
    for ($try = 1; $try -le 4 -and -not $ok; $try++) {
      try { $n = $fs.Read($buf, 0, $want); $ok = $true }
      catch {
        Log ("read error at offset {0:n0} (try {1}/4): {2}" -f $done, $try, $_.Exception.Message)
        Start-Sleep -Milliseconds 400
        try { $fs.Position = $done } catch {}   # re-seek and retry the same block
      }
    }
    if (-not $ok) { $badOffsets += $done; Log ("GIVING UP on block at {0:n0} after 4 tries" -f $done); break }
    if ($n -le 0) { break }
    $sha.TransformBlock($buf, 0, $n, $null, 0) | Out-Null
    $done += $n
    if ($done -ge $nextReport) {
      Log ("read: {0}%  {1} / {2} GB  {3} MB/s" -f [math]::Round(100.0*$done/$imgSize,1),[math]::Round($done/1GB,1),[math]::Round($imgSize/1GB,1),[math]::Round(($done/1MB)/$sw.Elapsed.TotalSeconds,1))
      $nextReport += 4GB
    }
  }
} finally { $sha.TransformFinalBlock($buf,0,0) | Out-Null; $fs.Dispose(); $h.Dispose() }

if ($badOffsets.Count -gt 0) {
  Log ("READ FAILED at offset(s): {0}" -f ($badOffsets -join ', '))
  Log ("read {0:n0} of {1:n0} bytes before the unreadable block." -f $done, $imgSize)
  Log 'RESULT: card has an unreadable sector (see offset). Re-run to see if the offset is stable (real bad block) or moves/clears (transient).'
  exit 20
}
$cardHash = ([BitConverter]::ToString($sha.Hash) -replace '-').ToLower()
Log ("image sha256: {0}" -f $imgHash)
Log ("card  sha256: {0}" -f $cardHash)
if ($imgHash -eq $cardHash) { Log 'VERIFY OK: card matches image.'; exit 0 }
else { Log 'VERIFY FAILED: full read succeeded but hashes differ (data mismatch).'; exit 21 }

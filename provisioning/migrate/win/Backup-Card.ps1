<#
.SYNOPSIS
  Read a removable SD card to a raw disk image (backup). Read-only on the card.

.DESCRIPTION
  Part of the ECO gateway migration tooling. Opens \\.\PHYSICALDRIVE<n> read-only
  and streams every byte to -OutFile in 8 MB chunks. Requires an elevated
  (Administrator) session - raw disk access needs it.

  Uses the approach proven on this machine (iotgw.img, sd-card.img):
    * FileStream opened directly on the device path with [IO.FileAccess]::Read
      (read-only by construction - it cannot damage the card),
    * byte count taken from Win32_DiskDrive.Size, which is the actually-readable
      extent. Get-Disk.Size can report a slightly larger value (~12 MB more on
      this reader) and reading that tail fails.

  HARD SAFETY GUARDS: refuses the system/boot disk; refuses a non-removable disk
  unless -Force; refuses to overwrite an existing non-empty output file.

  Every failure is logged - this script never dies silently.

.EXAMPLE
  .\Backup-Card.ps1 -DiskNumber 1 -OutFile C:\Users\me\sdcard\fh-pi.img
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][int]$DiskNumber,
  [Parameter(Mandatory)][string]$OutFile,
  [string]$LogFile,
  [switch]$Force,        # allow a non-removable disk (still never system/boot)
  [switch]$SkipHash
)

$ErrorActionPreference = 'Stop'
if (-not $LogFile) { $LogFile = [IO.Path]::ChangeExtension($OutFile, $null).TrimEnd('.') + '-imaging.log' }

function Log([string]$m) {
  $line = ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $m)
  Write-Host $line
  Add-Content -Path $LogFile -Value $line -Encoding utf8
}

Set-Content -Path $LogFile -Value ('imaging started {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8

try {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  Log ("elevated: {0}" -f $isAdmin)
  if (-not $isAdmin) { Log 'ERROR: not elevated - raw disk read needs Administrator.'; exit 2 }

  $disk = Get-Disk -Number $DiskNumber
  $phys = Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $DiskNumber
  if (-not $phys) { Log ("ERROR: no Win32_DiskDrive with Index {0}" -f $DiskNumber); exit 8 }

  $sig = if ($disk.Signature) { "0x{0:x8}" -f $disk.Signature } else { 'n/a' }
  Log ("target : disk {0}  {1}GB  bus={2}  system={3}  boot={4}  mbr-sig={5}  '{6}'" -f `
        $disk.Number, [math]::Round($disk.Size/1GB,2), $disk.BusType, $disk.IsSystem, $disk.IsBoot, $sig, $disk.FriendlyName)

  if ($disk.IsSystem -or $disk.IsBoot) { Log 'REFUSING: target is the system/boot disk.'; exit 3 }
  $removable = ($phys.MediaType -match 'Removable') -or ($disk.BusType -in 'USB','SD')
  Log ("media  : {0}  (removable={1})" -f $phys.MediaType, $removable)
  if (-not $removable -and -not $Force) { Log 'REFUSING: target is not removable (use -Force to override).'; exit 4 }

  if (Test-Path $OutFile) {
    $existing = (Get-Item $OutFile).Length
    if ($existing -gt 0) { Log ("ERROR: {0} already exists ({1:n0} bytes) - refusing to overwrite." -f $OutFile,$existing); exit 5 }
    Log 'note: removing empty leftover output file'
    Remove-Item $OutFile -Force
  }

  # Disk extent. Win32_DiskDrive.Size rounds DOWN to whole cylinders and can
  # under-report (897,024 bytes short on this reader), which silently truncates
  # the tail of the last partition. Get-Disk.Size is authoritative; take the
  # larger of the two so we never cut the filesystem short.
  $sizeGD  = [int64]$disk.Size
  $sizeW32 = [int64]$phys.Size
  $size    = [int64][math]::Max([int64]$sizeGD, [int64]$sizeW32)
  Log ("size   : Get-Disk={0:n0}  Win32={1:n0}  using={2:n0}" -f $sizeGD, $sizeW32, $size)
  if ($size -le 0) { Log 'ERROR: could not determine disk size.'; exit 9 }
  if ($size % 512 -ne 0) {
    $size = [int64]([math]::Floor($size / 512) * 512)
    Log ("adjusted to sector boundary: {0:n0}" -f $size)
  }
  Log ("reading {0:n0} bytes -> {1}" -f $size, $OutFile)

  $path = '\\.\PHYSICALDRIVE{0}' -f $DiskNumber
  # read-only, share read+write so a mounted volume does not block us
  $in  = New-Object System.IO.FileStream($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  $out = [System.IO.File]::Create($OutFile, 8MB)
  $buf = New-Object byte[] (8MB)
  $total = [int64]0
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $nextReport = 2GB
  try {
    while ($total -lt $size) {
      # both args must be Int64 or PowerShell binds Min(int,int) and overflows
      $want = [int][math]::Min([int64]$buf.Length, [int64]($size - $total))
      try {
        $n = $in.Read($buf, 0, $want)
      } catch {
        # Get-Disk can overshoot the readable extent by a sliver. Tolerate that
        # at the very tail; anything earlier is a real failure.
        $left = $size - $total
        if ($left -le 8MB) { Log ("note: read error {0:n0} bytes from the end - treating as end of media ({1})" -f $left, $_.Exception.Message); break }
        throw
      }
      if ($n -le 0) { Log ("read returned {0} at offset {1:n0} - stopping" -f $n, $total); break }
      $out.Write($buf, 0, $n)
      $total += $n
      if ($total -ge $nextReport) {
        $pct  = [math]::Round(100.0*$total/$size,1)
        $mbps = [math]::Round(($total/1MB)/$sw.Elapsed.TotalSeconds,1)
        $eta  = if ($mbps -gt 0) { [math]::Round((($size-$total)/1MB)/$mbps/60,1) } else { 0 }
        Log ("progress: {0}%  {1} / {2} GB  {3} MB/s  ETA {4} min" -f `
              $pct, [math]::Round($total/1GB,1), [math]::Round($size/1GB,2), $mbps, $eta)
        $nextReport += 2GB
      }
    }
  } finally {
    $out.Flush(); $out.Dispose(); $in.Dispose()
  }
  Log ("wrote {0:n0} bytes in {1:n0}s" -f $total, [math]::Round($sw.Elapsed.TotalSeconds))
  if ($total -ne $size) { Log ("WARNING: read {0:n0} of {1:n0} bytes" -f $total,$size) }

  if (-not $SkipHash) {
    Log 'hashing (sha256)...'
    $hash = (Get-FileHash -Path $OutFile -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path ($OutFile + '.sha256') -Value ("{0}  {1}" -f $hash, [IO.Path]::GetFileName($OutFile)) -Encoding ascii
    Log ("sha256: {0}" -f $hash)
  }
  Log ("mbr-sig (record this to tell same-size cards apart later): {0}" -f $sig)
  Log 'SUCCESS'
}
catch {
  Log ("FAILED: {0}" -f $_.Exception.Message)
  Log ("at: {0}" -f $_.InvocationInfo.PositionMessage)
  exit 1
}

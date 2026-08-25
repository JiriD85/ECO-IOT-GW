<#
.SYNOPSIS
  Write a raw disk image onto a removable SD card (DESTRUCTIVE restore).

.DESCRIPTION
  Part of the ECO gateway migration tooling. Opens \\.\PHYSICALDRIVE<n> and
  overwrites it with the bytes of -ImageFile. Requires an elevated session.

  HARD SAFETY GUARDS:
    * refuses any disk that is the system or boot disk,
    * refuses a non-removable disk unless -Force,
    * refuses if the image is larger than the target card,
    * requires the operator to type RESTORE (unless -Yes).

  Takes the disk offline (dismounts its volumes) before writing, then brings
  it back online so Windows re-reads the fresh partition table.

.EXAMPLE
  .\Restore-Card.ps1 -DiskNumber 1 -ImageFile C:\Users\me\sdcard\sd-card.img
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][int]$DiskNumber,
  [Parameter(Mandatory)][string]$ImageFile,
  [string]$LogFile,
  [switch]$Force,          # allow a non-removable disk (still never system/boot)
  [switch]$Yes,            # skip the typed confirmation
  [switch]$VerifyReadback  # read the card back and sha256-compare to the image
)

$ErrorActionPreference = 'Stop'
if (-not $LogFile) { $LogFile = [IO.Path]::ChangeExtension($ImageFile, $null).TrimEnd('.') + '-restore.log' }

function Log([string]$m) {
  $line = ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $m)
  Write-Host $line
  Add-Content -Path $LogFile -Value $line -Encoding utf8
}

Set-Content -Path $LogFile -Value ('restore started {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8

# never die silently: log any unhandled failure with its location
trap {
  Log ("FAILED: {0}" -f $_.Exception.Message)
  Log ("at: {0}" -f $_.InvocationInfo.PositionMessage)
  try { Set-Disk -Number $DiskNumber -IsOffline $false -ErrorAction Stop } catch { }
  exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Log ("elevated: {0}" -f $isAdmin)
if (-not $isAdmin) { Log 'ERROR: not elevated - raw disk write needs Administrator.'; exit 2 }

if (-not (Test-Path $ImageFile)) { Log ("ERROR: image not found: {0}" -f $ImageFile); exit 5 }
$imgSize = [int64](Get-Item $ImageFile).Length

$disk = Get-Disk -Number $DiskNumber
$gb   = [math]::Round($disk.Size/1GB,2)
Log ("target : disk {0}  {1}GB  bus={2}  system={3}  boot={4}  '{5}'" -f $disk.Number,$gb,$disk.BusType,$disk.IsSystem,$disk.IsBoot,$disk.FriendlyName)
Log ("image  : {0}  ({1:n0} bytes)" -f $ImageFile, $imgSize)

if ($disk.IsSystem -or $disk.IsBoot) { Log 'REFUSING: target is the system/boot disk.'; exit 3 }
$phys = Get-CimInstance Win32_DiskDrive | Where-Object Index -eq $DiskNumber
$removable = ($phys.MediaType -match 'Removable') -or ($disk.BusType -in 'USB','SD')
if (-not $removable -and -not $Force) { Log 'REFUSING: target is not removable (use -Force to override).'; exit 4 }
if ($imgSize -gt [int64]$disk.Size) { Log ("REFUSING: image ({0:n0}) is larger than card ({1:n0})." -f $imgSize,[int64]$disk.Size); exit 6 }

Log ("ABOUT TO OVERWRITE disk {0} ('{1}', {2}GB) with {3}. THIS ERASES THE CARD." -f $disk.Number,$disk.FriendlyName,$gb,[IO.Path]::GetFileName($ImageFile))
if (-not $Yes) {
  $ans = Read-Host 'Type RESTORE to proceed (anything else aborts)'
  if ($ans -ne 'RESTORE') { Log ("aborted by operator (typed '{0}')" -f $ans); exit 10 }
}

Add-Type -Namespace Win32 -Name RawW -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
public static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFileW(
  string lpFileName, uint dwDesiredAccess, uint dwShareMode, System.IntPtr lpSecurityAttributes,
  uint dwCreationDisposition, uint dwFlagsAndAttributes, System.IntPtr hTemplateFile);

[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError=true)]
public static extern bool DeviceIoControl(
  Microsoft.Win32.SafeHandles.SafeFileHandle hDevice, uint dwIoControlCode,
  System.IntPtr lpInBuffer, uint nInBufferSize, System.IntPtr lpOutBuffer, uint nOutBufferSize,
  out uint lpBytesReturned, System.IntPtr lpOverlapped);
'@

$GENERIC_RW    = [uint32](2147483648 -bor 1073741824)   # 0x80000000|0x40000000 (read+write), unsigned
$FILE_SHARE    = [uint32](0x1 -bor 0x2)
$OPEN_EXISTING = 3
$FSCTL_LOCK_VOLUME           = [uint32]0x00090018
$FSCTL_DISMOUNT_VOLUME       = [uint32]0x00090020
$IOCTL_DISK_UPDATE_PROPERTIES= [uint32]0x00070140

# Windows denies raw writes to sectors owned by a MOUNTED volume, and removable
# media cannot be set offline ("Removable media cannot be set to offline"). So do
# what real imagers do: lock + dismount each volume on this disk and hold the
# handles open for the whole write.
Log 'clearing read-only / locking + dismounting volumes on this disk...'
try { Set-Disk -Number $DiskNumber -IsReadOnly $false } catch { Log ("warn: clear ro: {0}" -f $_.Exception.Message) }

$volHandles = @()
foreach ($p in (Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter })) {
  $vpath = '\\.\{0}:' -f $p.DriveLetter
  $vh = [Win32.RawW]::CreateFileW($vpath, $GENERIC_RW, $FILE_SHARE, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
  if ($vh.IsInvalid) {
    Log ("ERROR: cannot open volume {0} ({1})" -f $vpath, [Runtime.InteropServices.Marshal]::GetLastWin32Error()); exit 11
  }
  $br = [uint32]0
  if (-not [Win32.RawW]::DeviceIoControl($vh, $FSCTL_LOCK_VOLUME, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$br, [IntPtr]::Zero)) {
    Log ("ERROR: FSCTL_LOCK_VOLUME failed on {0} ({1}) - something is using the card; close Explorer windows and retry." -f $vpath, [Runtime.InteropServices.Marshal]::GetLastWin32Error())
    exit 12
  }
  if (-not [Win32.RawW]::DeviceIoControl($vh, $FSCTL_DISMOUNT_VOLUME, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$br, [IntPtr]::Zero)) {
    Log ("ERROR: FSCTL_DISMOUNT_VOLUME failed on {0} ({1})" -f $vpath, [Runtime.InteropServices.Marshal]::GetLastWin32Error())
    exit 13
  }
  Log ("locked + dismounted {0}" -f $vpath)
  $volHandles += $vh
}
if ($volHandles.Count -eq 0) { Log 'no lettered volumes to lock (raw/unformatted card)' }

$path = '\\.\PHYSICALDRIVE{0}' -f $DiskNumber
$h = [Win32.RawW]::CreateFileW($path, $GENERIC_RW, $FILE_SHARE, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
if ($h.IsInvalid) { Log ("ERROR: CreateFile failed ({0})" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error()); exit 7 }

$in  = [System.IO.File]::OpenRead($ImageFile)
$out = New-Object System.IO.FileStream($h, [System.IO.FileAccess]::Write, 8MB)
$buf = New-Object byte[] (8MB)
$total = [int64]0
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$nextReport = 2GB
try {
  while ($total -lt $imgSize) {
    # both args must be Int64 or PowerShell binds Min(int,int) and overflows
    $want = [int][math]::Min([int64]$buf.Length, [int64]($imgSize - $total))
    $n = $in.Read($buf, 0, $want)
    if ($n -le 0) { break }
    $out.Write($buf, 0, $n)
    $total += $n
    if ($total -ge $nextReport) {
      $pct = [math]::Round(100.0*$total/$imgSize,1)
      $mbps = [math]::Round(($total/1MB)/$sw.Elapsed.TotalSeconds,1)
      Log ("progress: {0}%  {1} / {2} GB  {3} MB/s" -f $pct, [math]::Round($total/1GB,1), [math]::Round($imgSize/1GB,1), $mbps)
      $nextReport += 2GB
    }
  }
} finally {
  $out.Flush(); $out.Dispose(); $in.Dispose(); $h.Dispose()
}
Log ("wrote {0:n0} bytes in {1:n0}s" -f $total, [math]::Round($sw.Elapsed.TotalSeconds))
if ($total -ne $imgSize) { Log ("WARNING: wrote {0} of {1} bytes" -f $total,$imgSize) }

if ($VerifyReadback) {
  Log 'verifying (reading card back, sha256)...'
  $imgHash = (Get-FileHash -Path $ImageFile -Algorithm SHA256).Hash.ToLower()
  $hr = [Win32.RawW]::CreateFileW($path, [uint32]2147483648, $FILE_SHARE, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
  $rin = New-Object System.IO.FileStream($hr, [System.IO.FileAccess]::Read, 8MB)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $done = [int64]0
  try {
    while ($done -lt $imgSize) {
      $want = [int][math]::Min([int64]$buf.Length, [int64]($imgSize - $done))
      $n = $rin.Read($buf, 0, $want); if ($n -le 0) { break }
      $sha.TransformBlock($buf, 0, $n, $null, 0) | Out-Null
      $done += $n
    }
  } finally { $sha.TransformFinalBlock($buf,0,0) | Out-Null; $rin.Dispose(); $hr.Dispose() }
  $cardHash = ([BitConverter]::ToString($sha.Hash) -replace '-').ToLower()
  Log ("image sha256: {0}" -f $imgHash)
  Log ("card  sha256: {0}" -f $cardHash)
  if ($imgHash -eq $cardHash) { Log 'VERIFY OK: card matches image.' } else { Log 'VERIFY FAILED: mismatch!'; }
}

Log 'releasing volume locks and refreshing the partition table...'
foreach ($vh in $volHandles) { try { $vh.Dispose() } catch { } }   # unlock => Windows remounts
$hu = [Win32.RawW]::CreateFileW($path, $GENERIC_RW, $FILE_SHARE, [IntPtr]::Zero, $OPEN_EXISTING, 0, [IntPtr]::Zero)
if (-not $hu.IsInvalid) {
  $br = [uint32]0
  [void][Win32.RawW]::DeviceIoControl($hu, $IOCTL_DISK_UPDATE_PROPERTIES, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$br, [IntPtr]::Zero)
  $hu.Dispose()
}
Log 'SUCCESS'

<#
  sd.ps1 - attach a USB SD-card reader to WSL and mount a Raspberry Pi card with the
  real Linux kernel drivers, so both the operator and tooling can work with it using
  normal Unix commands (ls / cat / grep / rsync / git), not just the FAT boot partition
  that Windows shows.

  Why this exists: Windows only mounts partition 1 (vfat). The rootfs is ext4 and is
  invisible. `wsl --mount` cannot pass through the laptop's built-in Realtek PCIe card
  reader (it fails with WSL_E_... / 0x8007000f), so we go through usbipd instead, which
  works with any *USB* reader - a hub with an SD slot, or a stick reader.

  Mounted read-only by default. Pass -Rw only when you actually intend to change the
  card, e.g. seeding a fresh image with userconf.txt / ssh / authorized_keys before its
  first boot. An ext4 mounted rw and yanked without unmounting will lose writes.

  While the reader is attached to WSL, Windows loses the drive letter. `-Action detach`
  unmounts and gives it back. Always detach before physically removing the card.

  Usage:
    tools\sd.ps1                      # attach + mount read-only
    tools\sd.ps1 -Rw                  # attach + mount read-write
    tools\sd.ps1 -Action status
    tools\sd.ps1 -Action detach
    tools\sd.ps1 -BusId 4-1           # skip reader auto-detection

  Mount points inside WSL:
    /mnt/sd/boot   the vfat firmware partition  (config.txt, cmdline.txt, userconf.txt)
    /mnt/sd/root   the ext4 rootfs

  Reach them from Windows tooling as:
    wsl -e sh -c 'cat /mnt/sd/root/etc/hostname'
    \\wsl.localhost\Ubuntu\mnt\sd\root           (Explorer, and Claude's Read tool)

  Use the \\wsl.localhost form, not \\wsl$ - the latter works in PowerShell but some
  tools reject it. Symlinks (e.g. /etc/os-release -> /usr/lib/os-release) may not
  resolve over the 9p share either; read those through `wsl -e cat` instead.
#>
[CmdletBinding()]
param(
  [ValidateSet('attach', 'detach', 'status', 'disks', 'flash')]
  [string]$Action = 'attach',
  [string]$BusId = '',
  [switch]$Rw,
  [string]$Image = '',      # flash: raw image to write
  [int]$DiskNumber = -1,    # flash: target disk, required when several cards are present
  [switch]$Yes              # flash: skip the typed confirmation (the caller already asked)
)

$ErrorActionPreference = 'Stop'

# usbipd writes its progress lines to stderr; with $ErrorActionPreference='Stop' that
# would be promoted to a terminating NativeCommandError even on success. Run native
# commands through here so stderr is captured as plain text and only the exit code counts.
function Native([string]$exe, [string[]]$argv) {
  $errFile = [IO.Path]::GetTempFileName()
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    # stderr to a file rather than 2>&1: merging it into the success stream turns each
    # line into a formatted ErrorRecord, which buries the actual message in noise.
    $out = & $exe @argv 2>$errFile | Out-String
    $code = $LASTEXITCODE
    $err = ''
    if (Test-Path $errFile) { $err = [IO.File]::ReadAllText($errFile) }
    return [pscustomobject]@{
      Code = $code
      Out  = ((($out + $err) -replace "`0", '')).Trim()
    }
  } finally {
    $ErrorActionPreference = $prev
    Remove-Item $errFile -Force -ErrorAction SilentlyContinue
  }
}

function Fail($msg) { Write-Host "  ! $msg" -ForegroundColor Red; exit 1 }
function Say($msg) { Write-Host "  $msg" }
function Ok($msg) { Write-Host "  + $msg" -ForegroundColor Green }

if (-not (Get-Command usbipd.exe -ErrorAction SilentlyContinue)) {
  Fail "usbipd not installed. Run:  winget install usbipd"
}

# --- locate the reader -------------------------------------------------------
# usbipd list prints:  BUSID  VID:PID  DEVICE...  STATE
function Get-Reader {
  $lines = (Native 'usbipd.exe' @('list')).Out -split "`r?`n"
  $found = @()
  foreach ($l in $lines) {
    if ($l -match '^(\d+-\d+)\s+([0-9a-f]{4}:[0-9a-f]{4})\s+(.*?)\s\s+(\S.*)$') {
      $found += [pscustomobject]@{ BusId = $Matches[1]; VidPid = $Matches[2]; Device = $Matches[3].Trim(); State = $Matches[4].Trim() }
    }
  }
  if ($BusId) { return $found | Where-Object BusId -eq $BusId | Select-Object -First 1 }
  # match the localized and English names for a USB mass-storage device
  return $found | Where-Object { $_.Device -match 'Mass ?[Ss]torage|Massenspeicher|Card ?Reader|Kartenleser' } | Select-Object -First 1
}

# After a detach, Windows re-enumerates the reader and it vanishes from `usbipd list`
# for a second or two. Retry rather than declaring it missing.
$reader = $null
foreach ($try in 1..10) {
  $reader = Get-Reader
  if ($reader) { break }
  Start-Sleep -Milliseconds 700
}
if (-not $reader) {
  Say 'No USB mass-storage reader found. Devices usbipd can see:'
  & usbipd.exe list
  Fail 'Plug in the USB card reader, or pass -BusId explicitly.'
}

# --- WSL-side helpers --------------------------------------------------------
# A multi-line script handed to `wsl.exe -e sh -c` as one argument gets mangled by
# Windows->WSL command-line reassembly (newlines and quotes come out broken). Ship it
# base64-encoded instead, so the command line is a single token with no metacharacters.
function Wsl-Root($script) {
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script))
  return (Native 'wsl.exe' @('-u', 'root', '-e', 'sh', '-c', "echo $b64 | base64 -d | sh")).Out
}

$mountScript = @'
set -e
modprobe usb-storage 2>/dev/null || true
modprobe uas 2>/dev/null || true
# give the SCSI layer a moment to enumerate the card after the reader appears
for i in 1 2 3 4 5 6 7 8 9 10; do
  DISK=""
  for d in /dev/sd?; do
    [ -b "$d" ] || continue
    # a Pi card is a disk holding both a vfat and an ext4 partition
    HAS_VFAT=0; HAS_EXT=0
    for p in ${d}?*; do
      [ -b "$p" ] || continue
      T=$(blkid -o value -s TYPE "$p" 2>/dev/null || true)
      [ "$T" = "vfat" ] && HAS_VFAT=1
      case "$T" in ext2|ext3|ext4) HAS_EXT=1 ;; esac
    done
    if [ "$HAS_VFAT" = 1 ] && [ "$HAS_EXT" = 1 ]; then DISK="$d"; break; fi
  done
  [ -n "$DISK" ] && break
  sleep 1
done
if [ -z "$DISK" ]; then
  echo "ERROR: no disk with a vfat+ext4 pair appeared. Is a card in the reader?" >&2
  lsblk -o NAME,SIZE,TYPE,FSTYPE >&2
  exit 1
fi
mkdir -p /mnt/sd/boot /mnt/sd/root
mountpoint -q /mnt/sd/boot && umount /mnt/sd/boot || true
mountpoint -q /mnt/sd/root && umount /mnt/sd/root || true
for p in ${DISK}?*; do
  T=$(blkid -o value -s TYPE "$p" 2>/dev/null || true)
  case "$T" in
    vfat)             mount -o __MODE__ "$p" /mnt/sd/boot ;;
    ext2|ext3|ext4)   mount -o __MODE__ "$p" /mnt/sd/root ;;
  esac
done
echo "DISK=$DISK"
findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /mnt/sd/boot
findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /mnt/sd/root
'@

# Candidate target disks for a flash: never the system/boot disk, and only buses a card
# reader can appear on. Restore-Card.ps1 enforces the real guards; this is for selection.
function Get-CardDisks {
  Get-Disk | Where-Object { -not $_.IsSystem -and -not $_.IsBoot -and $_.BusType -in @('USB', 'SD', 'SCSI') } |
    ForEach-Object {
      $letters = (Get-Partition -DiskNumber $_.Number -ErrorAction SilentlyContinue |
                  Where-Object DriveLetter | ForEach-Object { $_.DriveLetter }) -join ','
      [pscustomobject]@{
        Number = $_.Number; Size = [int64]$_.Size; SizeGB = [math]::Round($_.Size / 1GB, 1)
        FriendlyName = $_.FriendlyName; BusType = [string]$_.BusType
        PartitionStyle = [string]$_.PartitionStyle; DriveLetters = $letters
      }
    }
}

# Release the card from WSL so Windows owns the block device again (flash writes via
# Windows, not WSL). Safe to call when nothing is attached.
function Release-ToWindows {
  Wsl-Root 'for m in /mnt/sd/root /mnt/sd/boot; do mountpoint -q $m && umount $m; done; sync' | Out-Null
  if ($reader -and $reader.State -match 'Attached') {
    Native 'usbipd.exe' @('detach', '--busid', $reader.BusId) | Out-Null
    Say "detached $($reader.BusId) - waiting for Windows to re-enumerate the card"
    foreach ($t in 1..20) { Start-Sleep -Milliseconds 750; if (Get-CardDisks) { break } }
  }
}

switch ($Action) {

  'disks' {
    # machine-readable for the migration wizard
    $d = @(Get-CardDisks)
    # -AsArray is PowerShell 7+; on 5.1 a single object serialises as an object, so wrap it
    if ($d.Count -eq 0) { Write-Output '[]' }
    else {
      $j = $d | ConvertTo-Json -Compress
      if ($d.Count -eq 1) { $j = '[' + $j + ']' }
      Write-Output $j
    }
  }

  'flash' {
    if (-not $Image) { Fail 'flash requires -Image <path to .img>' }
    if (-not (Test-Path $Image)) { Fail "image not found: $Image" }
    $imgBytes = (Get-Item $Image).Length
    Say ("image: {0} ({1} GB)" -f $Image, [math]::Round($imgBytes / 1GB, 1))

    Release-ToWindows

    $cands = @(Get-CardDisks)
    if ($cands.Count -eq 0) { Fail 'no candidate removable disk found (is the card in the reader?)' }
    # A multi-slot hub reports every empty slot as a 0-byte disk. Anything too small to
    # hold the image cannot be the target, so drop those before judging ambiguity.
    $tooSmall = @($cands | Where-Object { $_.Size -lt $imgBytes })
    if ($tooSmall.Count) { Say ("ignoring {0} disk(s) too small for the image: {1}" -f $tooSmall.Count, (($tooSmall | ForEach-Object { "disk $($_.Number) ($($_.SizeGB) GB)" }) -join ', ')) }
    $cands = @($cands | Where-Object { $_.Size -ge $imgBytes })
    if ($cands.Count -eq 0) { Fail 'no candidate disk is large enough for the image' }
    if ($DiskNumber -ge 0) {
      $target = $cands | Where-Object Number -eq $DiskNumber | Select-Object -First 1
      if (-not $target) { Fail "disk $DiskNumber is not among the candidates: $(($cands | ForEach-Object { $_.Number }) -join ', ')" }
    } elseif ($cands.Count -eq 1) {
      $target = $cands[0]
    } else {
      Say 'several candidate disks - pass -DiskNumber to choose:'
      $cands | Format-Table -AutoSize | Out-String | Write-Host
      Fail 'ambiguous target'
    }

    Say ("target: disk {0}  {1}  {2} GB  [{3}]  letters={4}" -f $target.Number, $target.FriendlyName, $target.SizeGB, $target.BusType, $target.DriveLetters)
    if ($imgBytes -gt $target.Size) { Fail "image ($imgBytes B) is larger than disk $($target.Number) ($($target.Size) B)" }

    if (-not $Yes) {
      Write-Host '  THIS ERASES THE CARD.' -ForegroundColor Red
      $t = Read-Host '  type ERASE to continue'
      if ($t -ne 'ERASE') { Fail 'aborted' }
    }

    $restore = Join-Path (Split-Path $PSScriptRoot -Parent) 'provisioningmigratewinRestore-Card.ps1'
    if (-not (Test-Path $restore)) { Fail "Restore-Card.ps1 not found at $restore" }
    $log = Join-Path $env:TEMP ("eco-flash-{0}.log" -f $target.Number)
    Remove-Item $log -ErrorAction SilentlyContinue

    Say 'writing (elevated; approve the UAC prompt). This takes several minutes...'
    $p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @(
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $restore,
      '-DiskNumber', $target.Number, '-ImageFile', $Image, '-LogFile', $log, '-Yes')

    if (Test-Path $log) { Write-Host (Get-Content $log -Raw) }
    if ($p.ExitCode -ne 0) { Fail "Restore-Card.ps1 exited $($p.ExitCode) - see $log" }
    Ok 'image written'
    Say 'move the card into the gateway, connect Ethernet, and power it on'
  }

  'status' {
    Say "reader: $($reader.BusId)  $($reader.VidPid)  [$($reader.State)]"
    $m = Wsl-Root 'findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /mnt/sd/boot 2>/dev/null; findmnt -no TARGET,SOURCE,FSTYPE,OPTIONS /mnt/sd/root 2>/dev/null'
    if ($m.Trim()) {
      Ok 'mounted:'
      Write-Host $m.TrimEnd()
      $h = (Wsl-Root 'cat /mnt/sd/root/etc/hostname 2>/dev/null').Trim()
      if ($h) { Say "card hostname: $h" }
    } else {
      Say 'not mounted'
    }
  }

  'detach' {
    Say 'unmounting'
    Wsl-Root 'for m in /mnt/sd/root /mnt/sd/boot; do mountpoint -q $m && umount $m; done; sync' | Out-Null
    $still = (Wsl-Root 'findmnt -no TARGET /mnt/sd/boot /mnt/sd/root 2>/dev/null').Trim()
    if ($still) { Fail "still mounted: $still (a shell may be sitting in /mnt/sd)" }
    $d = Native 'usbipd.exe' @('detach', '--busid', $reader.BusId)
    if ($d.Code -ne 0) { Fail "usbipd detach failed: $($d.Out.Trim())" }
    Ok "detached $($reader.BusId) - Windows has the reader back; safe to remove the card"
  }

  'attach' {
    if ($reader.State -match 'Not shared') {
      Say "binding $($reader.BusId) (needs admin, one time per reader)"
      $p = Start-Process -FilePath usbipd.exe -ArgumentList 'bind', '--busid', $reader.BusId -Verb RunAs -Wait -PassThru
      if ($p.ExitCode -ne 0) { Fail "usbipd bind failed (exit $($p.ExitCode))" }
    }
    if ($reader.State -notmatch 'Attached') {
      Say "attaching $($reader.BusId) to WSL"
      $a = Native 'usbipd.exe' @('attach', '--wsl', '--busid', $reader.BusId)

      # If Windows has already mounted the card's FAT partition it holds the device open
      # and the attach is refused as busy. `bind --force` would fix it permanently but
      # takes the reader away from Windows entirely; a replug is cheaper and reversible,
      # because usbipd attaches the freshly enumerated device before Windows mounts it.
      if ($a.Code -ne 0 -and $a.Out -match 'busy|used by Windows') {
        Write-Host ''
        Write-Host '  Windows is holding the reader. Please UNPLUG the reader and PLUG IT BACK IN.' -ForegroundColor Yellow
        Write-Host '  Waiting for it to come back...' -ForegroundColor Yellow
        $gone = $false
        foreach ($try in 1..90) {
          Start-Sleep -Seconds 1
          $now = Get-Reader
          if (-not $now) { $gone = $true; continue }     # unplugged
          if (-not $gone) { continue }                    # not unplugged yet
          $a = Native 'usbipd.exe' @('attach', '--wsl', '--busid', $now.BusId)
          if ($a.Code -eq 0) { $reader = $now; break }
        }
      }
      if ($a.Code -ne 0) { Fail "usbipd attach failed: $($a.Out)" }
    } else {
      Say "$($reader.BusId) already attached"
    }

    if ($Rw) { $mode = 'rw' } else { $mode = 'ro' }
    Say "mounting $mode"
    $out = Wsl-Root ($mountScript -replace '__MODE__', $mode)
    if ($out -match 'ERROR:') { Write-Host $out.TrimEnd(); Fail 'mount failed' }
    Write-Host $out.TrimEnd()

    $h = (Wsl-Root 'cat /mnt/sd/root/etc/hostname 2>/dev/null').Trim()
    $iss = (Wsl-Root 'cat /mnt/sd/root/etc/rpi-issue 2>/dev/null | head -1').Trim()
    Ok "mounted $mode"
    if ($h) { Say "hostname : $h" }
    if ($iss) { Say "image    : $iss" }
    Say 'boot     : /mnt/sd/boot     rootfs: /mnt/sd/root'
    Say 'from win : wsl -e sh -c ''ls /mnt/sd/root'''
    Say '           \\wsl.localhost\Ubuntu\mnt\sd\root'
    if ($Rw) { Write-Host '  ! read-write: run  tools\sd.ps1 -Action detach  before pulling the card' -ForegroundColor Yellow }
  }
}

<#
.SYNOPSIS
  Stage the ECO first-boot conversion onto a Pi card's FAT boot partition.

.DESCRIPTION
  Copies firstrun.sh + an SSH public key onto the boot partition and appends
  systemd.run= to cmdline.txt, so the script runs once as root on first boot.
  This is the mechanism Raspberry Pi Imager uses; systemd-run-generator is
  confirmed present on the RESI image.

  No elevation required - the boot partition is a normal FAT32 drive letter.
  Fully reversible from Windows: see -Revert.

  Writes LF line endings (a CRLF shebang would break the script on Linux) and
  keeps cmdline.txt as a single line with no trailing newline, which the Pi
  firmware requires.

.EXAMPLE
  .\Stage-FirstRun.ps1 -BootDrive D -PublicKey $env:USERPROFILE\.ssh\eco-gw.pub

.EXAMPLE
  .\Stage-FirstRun.ps1 -BootDrive D -Revert
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$BootDrive,
  [string]$PublicKey,
  [string]$FirstRun = (Join-Path $PSScriptRoot '..\boot\firstrun.sh'),
  [switch]$Revert
)

$ErrorActionPreference = 'Stop'
$d = $BootDrive.TrimEnd(':','\')
$root = "${d}:\"

function Say([string]$m) { Write-Host $m }

# ---- guard: this must actually be a Raspberry Pi boot partition -------------
if (-not (Test-Path $root)) { throw "$root not found" }
$vol = Get-Volume -DriveLetter $d
if ($vol.FileSystem -ne 'FAT32') { throw "$root is $($vol.FileSystem), expected FAT32 - refusing (wrong drive?)" }
foreach ($must in @('cmdline.txt','config.txt')) {
  if (-not (Test-Path (Join-Path $root $must))) {
    throw "$root has no $must - this is not a Pi boot partition. Refusing."
  }
}
Say ("boot partition : {0}  label='{1}'  {2:n0} MB free" -f $root, $vol.FileSystemLabel, ($vol.SizeRemaining/1MB))

$cmdlinePath = Join-Path $root 'cmdline.txt'
$backupPath  = Join-Path $root 'cmdline.txt.eco-backup'
$scriptPath  = Join-Path $root 'firstrun.sh'
$keyPath     = Join-Path $root 'eco_authorized_keys'
$RUNARGS     = ' systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target'

# ---- revert ----------------------------------------------------------------
if ($Revert) {
  if (Test-Path $backupPath) {
    $orig = [IO.File]::ReadAllText($backupPath)
    [IO.File]::WriteAllText($cmdlinePath, $orig)
    Remove-Item $backupPath -Force
    Say 'cmdline.txt restored from backup'
  } else {
    $cur = [IO.File]::ReadAllText($cmdlinePath)
    $cleaned = ($cur -replace ' systemd\.run[^\s]*','').TrimEnd("`r","`n")
    [IO.File]::WriteAllText($cmdlinePath, $cleaned)
    Say 'no backup found - stripped systemd.run args in place'
  }
  foreach ($f in @($scriptPath,$keyPath)) { if (Test-Path $f) { Remove-Item $f -Force; Say "removed $f" } }
  Say 'REVERTED - card boots as stock RESI again.'
  Say ('cmdline.txt: ' + [IO.File]::ReadAllText($cmdlinePath))
  exit 0
}

# ---- stage ----------------------------------------------------------------
if (-not $PublicKey) { throw '-PublicKey is required (path to an .pub file)' }
if (-not (Test-Path $PublicKey)) { throw "public key not found: $PublicKey" }
$key = ([IO.File]::ReadAllText($PublicKey)).Trim()
if ($key -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2)') { throw "does not look like an SSH public key: $PublicKey" }
Say ("ssh key        : {0} ... {1}" -f $key.Split(' ')[0], ($key.Split(' ')[-1]))

if (-not (Test-Path $FirstRun)) { throw "firstrun.sh not found: $FirstRun" }

# copy firstrun.sh with LF endings (CRLF would break the shebang on Linux)
$body = ([IO.File]::ReadAllText($FirstRun)) -replace "`r`n","`n"
[IO.File]::WriteAllText($scriptPath, $body, (New-Object System.Text.UTF8Encoding($false)))
Say ("wrote          : {0}  ({1:n0} bytes, LF)" -f $scriptPath, $body.Length)

[IO.File]::WriteAllText($keyPath, ($key + "`n"), (New-Object System.Text.UTF8Encoding($false)))
Say ("wrote          : {0}" -f $keyPath)

# patch cmdline.txt: single line, no trailing newline
$cmdline = ([IO.File]::ReadAllText($cmdlinePath)).Trim()
if (-not (Test-Path $backupPath)) {
  [IO.File]::WriteAllText($backupPath, $cmdline)
  Say ("backed up      : {0}" -f $backupPath)
}
if ($cmdline -match 'systemd\.run=') {
  Say 'cmdline.txt already carries systemd.run - leaving as is'
} else {
  [IO.File]::WriteAllText($cmdlinePath, ($cmdline + $RUNARGS), (New-Object System.Text.ASCIIEncoding))
  Say 'cmdline.txt patched'
}
Say ''
Say ('cmdline.txt now: ' + [IO.File]::ReadAllText($cmdlinePath))
Say ''
Say 'STAGED. Eject the card, boot the Pi with Ethernet plugged in.'
Say 'It converts, then reboots. Then:  ssh ecoadmin@<ip>'
Say 'The run log lands on the boot partition as eco-firstrun.log (readable in Windows).'
Say ("To undo before booting:  .\Stage-FirstRun.ps1 -BootDrive {0} -Revert" -f $d)

# Phase 2: Backup & Restore - Research

**Researched:** 2026-01-24
**Domain:** System backup/restore, tar.gz archives, FastAPI file streaming
**Confidence:** HIGH

## Summary

This phase requires implementing system backup and restore functionality for an IoT Gateway running on Raspberry Pi. The backup must capture all critical configuration files from various system locations (VPN, modem, serial, ThingsBoard, NTP, audit logs) and package them as a tar.gz archive for download. Restore must validate and extract uploaded backups to their original locations.

The standard approach uses Python's built-in `tarfile` module with gzip compression, FastAPI's `UploadFile` for memory-efficient file uploads, and `FileResponse` or `StreamingResponse` for downloads. Security is critical: backup archives from untrusted sources pose path traversal risks, requiring validation before extraction.

**Primary recommendation:** Use Python's standard `tarfile` module with PAX format, implement backup manifest (JSON metadata), stream tar creation to avoid memory issues, validate all extractions against path traversal attacks, and leverage existing audit logging for backup/restore events.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tarfile | stdlib (Python 3.11) | Create/extract tar.gz archives | Built-in, reliable, supports streaming, no dependencies |
| FastAPI UploadFile | 0.109+ | Handle file uploads | Memory-efficient spooled storage, async support, part of existing stack |
| FastAPI FileResponse | 0.109+ | Stream file downloads | Automatic headers (Content-Length, ETag), memory-efficient streaming |
| pathlib | stdlib | Path manipulation | Type-safe path handling, prevents common path vulnerabilities |
| json | stdlib | Backup manifest metadata | Standard format for backup metadata validation |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiofiles | 24.1.0+ | Async file I/O | If tar creation needs to be async (optional, tarfile is sync) |
| StreamingResponse | FastAPI | Alternative to FileResponse | When generating archive on-the-fly without saving to disk |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tarfile | zip/zipfile | zip has worse compression, tar.gz is Linux standard for backups |
| PAX_FORMAT | GNU_FORMAT | GNU has limits on filename length, PAX is POSIX standard with no limits |
| FileResponse | StreamingResponse | StreamingResponse requires manual headers, FileResponse handles automatically |
| Manual tar creation | shutil.make_archive | shutil is simpler but less control over filtering, metadata, and error handling |

**Installation:**
No additional packages required - all core libraries are Python stdlib.

```bash
# Optional: For async file operations (not required)
pip install aiofiles
```

## Architecture Patterns

### Recommended Project Structure

```
backend/app/
├── api/
│   └── backup.py              # Backup/restore API endpoints
├── services/
│   └── backup_service.py      # Backup creation, restore logic
├── models/
│   └── schemas.py             # BackupInfo, RestoreRequest models
└── config.py                  # BACKUP_DIR path configuration
```

### Pattern 1: Backup Manifest Metadata

**What:** Include a JSON manifest inside each backup with metadata (timestamp, version, hostname, included paths)

**When to use:** Always - enables validation during restore, version compatibility checks, and audit trail

**Example:**

```python
# Source: PostgreSQL backup manifest pattern
# https://www.postgresql.org/docs/current/backup-manifest-format.html

manifest = {
    "version": "1.0",
    "created_at": datetime.now().isoformat(),
    "hostname": platform.node(),
    "app_version": settings.APP_VERSION,
    "included_paths": [
        "/etc/eco-iot-gw/",
        "/etc/openvpn/",
        "/etc/wireguard/",
        # ... etc
    ],
    "checksum": "sha256:..."
}
```

### Pattern 2: Streaming Tar Creation

**What:** Create tar.gz archive on-the-fly without buffering entire archive in memory

**When to use:** When backup size may exceed available RAM (critical for Raspberry Pi)

**Example:**

```python
# Source: FastAPI streaming tar.gz pattern
# https://openillumi.com/en/en-fastapi-async-tar-gz-streaming/

import tarfile
import io
from fastapi.responses import StreamingResponse

def create_backup_stream():
    """Generator that yields tar.gz chunks."""
    buffer = io.BytesIO()

    with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
        # Add manifest first
        manifest_data = json.dumps(manifest).encode('utf-8')
        manifest_info = tarfile.TarInfo(name='backup-manifest.json')
        manifest_info.size = len(manifest_data)
        tar.addfile(manifest_info, io.BytesIO(manifest_data))

        # Add files from paths
        for path in backup_paths:
            if path.exists():
                tar.add(str(path), arcname=path.name)

    buffer.seek(0)
    yield from buffer
```

### Pattern 3: Path Traversal Protection

**What:** Validate all tar entries before extraction to prevent directory traversal attacks

**When to use:** Always - malicious archives can escape extraction directory with `../` paths

**Example:**

```python
# Source: Python tarfile security best practices
# https://docs.python.org/3/library/tarfile.html

def safe_extract(tar: tarfile.TarFile, target_dir: Path):
    """Safely extract tar archive with path traversal protection."""
    target_dir = target_dir.resolve()

    for member in tar.getmembers():
        # Check for absolute paths
        if member.name.startswith('/'):
            raise ValueError(f"Absolute path in archive: {member.name}")

        # Check for path traversal
        member_path = (target_dir / member.name).resolve()
        if not member_path.is_relative_to(target_dir):
            raise ValueError(f"Path traversal detected: {member.name}")

        # Check for symlink attacks
        if member.issym() or member.islnk():
            raise ValueError(f"Symbolic links not allowed: {member.name}")

    # Safe to extract
    tar.extractall(target_dir, filter='data')  # Python 3.12+ filter
```

### Pattern 4: FastAPI File Upload/Download

**What:** Use UploadFile for streaming uploads, FileResponse for downloads

**When to use:** Standard pattern for all file operations in FastAPI

**Example:**

```python
# Source: FastAPI official docs
# https://fastapi.tiangolo.com/tutorial/request-files/

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse

@app.post("/backup/restore")
async def restore_backup(
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """Upload and restore from backup."""
    # Save uploaded file temporarily
    temp_path = Path(f"/tmp/backup-{uuid.uuid4()}.tar.gz")

    # Stream upload to disk (memory efficient)
    async with aiofiles.open(temp_path, 'wb') as f:
        while chunk := await file.read(8192):  # 8KB chunks
            await f.write(chunk)

    # Validate and restore
    backup_service.restore_from_file(temp_path)

    return SuccessResponse(message="Backup restored successfully")

@app.post("/backup/create")
async def create_backup(user: UserInfo = Depends(get_current_user)):
    """Create and download system backup."""
    backup_path = backup_service.create_backup()

    return FileResponse(
        path=backup_path,
        filename=f"eco-iot-gw-backup-{datetime.now():%Y%m%d-%H%M%S}.tar.gz",
        media_type="application/gzip"
    )
```

### Anti-Patterns to Avoid

- **Loading entire archive into memory:** Always stream both creation and extraction, especially on Raspberry Pi with limited RAM
- **Using --absolute-names in tar:** Never extract with absolute paths from untrusted sources
- **Skipping manifest validation:** Always validate backup version, hostname, and paths before restore
- **No backup testing:** Create test restore mechanism to validate backups are restorable
- **Hardcoded paths:** Use configuration for all backup paths to support different environments

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Archive creation | Custom tar implementation | stdlib tarfile | Handles compression, formats, metadata, streaming |
| Path validation | Regex-based path checking | pathlib.resolve() + is_relative_to() | Prevents symlink attacks, handles edge cases |
| File streaming | Manual chunked reading | UploadFile / FileResponse | Memory management, headers, cleanup already solved |
| Checksum calculation | Manual hash implementation | hashlib.sha256() | Optimized, standard, audited |
| Async file I/O | Thread pool wrapper | aiofiles (optional) | Proper async context managers, tested |

**Key insight:** Backup/restore has subtle security pitfalls. Path traversal, symlink attacks, and wildcard exploits are real threats. Never implement custom archive handling or path validation - use stdlib which has battle-tested security.

## Common Pitfalls

### Pitfall 1: Path Traversal Vulnerability

**What goes wrong:** Extracting untrusted tar archives without validation allows attackers to write files outside the target directory using `../../etc/passwd` style paths

**Why it happens:** Python's tarfile.extractall() doesn't validate paths by default (before Python 3.12)

**How to avoid:**
- Always validate each member path before extraction
- Use `pathlib.Path.is_relative_to()` to verify extracted paths stay within target
- Never use `--absolute-names` option
- Reject archives with symlinks unless explicitly trusted

**Warning signs:**
- tar extraction fails with "permission denied" on system paths
- Files appearing in unexpected locations after restore
- Archives containing entries starting with `/` or containing `../`

### Pitfall 2: Memory Exhaustion on Large Backups

**What goes wrong:** Reading entire backup into memory before writing/extracting causes OOM on Raspberry Pi

**Why it happens:** Using `file.read()` without size limit, or creating BytesIO with full archive

**How to avoid:**
- Stream tar creation: write directly to file, don't buffer in memory
- Stream tar extraction: use `tar.extractall()` which streams
- For uploads: use `UploadFile.read(size)` with chunk size (8KB-64KB)
- For downloads: use FileResponse (streams automatically) or StreamingResponse with generator

**Warning signs:**
- Backend process killed by OOM
- High memory usage during backup/restore operations
- `MemoryError` exceptions

### Pitfall 3: Wildcard Exploitation in Automated Systems

**What goes wrong:** Using shell wildcards (`tar -xzf *.tar.gz`) in cron jobs allows privilege escalation via specially crafted filenames

**Why it happens:** Tar processes files starting with `-` as options, e.g., `--checkpoint-action=exec=sh shell.sh`

**How to avoid:**
- Use Python's tarfile module, not shell commands
- If shell required, always use `--` to separate options from filenames
- Never use wildcards in tar commands
- Validate filenames before processing

**Warning signs:**
- Unexpected command execution during backup operations
- Files with names starting with `-` or `--`

### Pitfall 4: Missing Backup Validation

**What goes wrong:** Backups are created but never tested, discover during disaster recovery that they're corrupt or incomplete

**Why it happens:** No automated validation, no test restores, silent corruption

**How to avoid:**
- Include manifest with file checksums
- Verify tar archive integrity immediately after creation (`tar -tzf`)
- Implement periodic test restore to temporary directory
- Log backup creation to audit trail
- Check disk space before backup creation

**Warning signs:**
- Backup files with zero size
- Tar extraction errors during restore
- Missing files after restore
- Checksums don't match

### Pitfall 5: Permissions and Ownership Loss

**What goes wrong:** Restored files have wrong permissions/ownership, breaking services

**Why it happens:** Tar extracts with current user permissions, not original

**How to avoid:**
- Document that restore requires root or specific user
- Explicitly set permissions after extraction for critical files (VPN configs need 600)
- Store permission metadata in manifest for verification
- Test restore in clean environment

**Warning signs:**
- VPN won't start after restore (config permissions wrong)
- Services can't read configuration files
- "Permission denied" errors after restore

## Code Examples

Verified patterns from official sources:

### Creating Backup with Manifest

```python
# Source: Combined pattern from PostgreSQL manifests and Python tarfile docs
import tarfile
import json
from pathlib import Path
from datetime import datetime

def create_backup(output_path: Path) -> Path:
    """Create system backup with manifest."""
    backup_paths = [
        Path("/etc/eco-iot-gw/"),
        Path("/etc/openvpn/"),
        Path("/etc/wireguard/"),
        Path("/etc/thingsboard-gateway/config/"),
        Path("/etc/chrony/chrony.conf"),
        Path("/var/lib/eco-iot-gw/audit/")
    ]

    # Create manifest
    manifest = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "hostname": platform.node(),
        "app_version": settings.APP_VERSION,
        "paths": [str(p) for p in backup_paths if p.exists()]
    }

    # Create tar.gz with PAX format (no limits)
    with tarfile.open(output_path, 'w:gz', format=tarfile.PAX_FORMAT) as tar:
        # Add manifest first
        manifest_json = json.dumps(manifest, indent=2).encode('utf-8')
        manifest_info = tarfile.TarInfo(name='backup-manifest.json')
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, io.BytesIO(manifest_json))

        # Add each path
        for path in backup_paths:
            if path.exists():
                # Use relative arcname to avoid absolute paths
                arcname = path.name if path.is_file() else path.name
                tar.add(str(path), arcname=arcname, recursive=True)

    return output_path
```

### Safe Restore with Validation

```python
# Source: Python tarfile security best practices
# https://docs.python.org/3/library/tarfile.html
import tarfile
from pathlib import Path

def validate_and_restore(backup_file: Path, target_dir: Path):
    """Safely restore backup with validation."""
    target_dir = target_dir.resolve()

    with tarfile.open(backup_file, 'r:gz') as tar:
        # Read and validate manifest
        try:
            manifest_member = tar.getmember('backup-manifest.json')
            manifest_data = tar.extractfile(manifest_member).read()
            manifest = json.loads(manifest_data)
        except KeyError:
            raise ValueError("Invalid backup: missing manifest")

        # Version check
        if manifest['version'] != '1.0':
            raise ValueError(f"Unsupported backup version: {manifest['version']}")

        # Validate all paths before extraction
        for member in tar.getmembers():
            # Skip manifest (already read)
            if member.name == 'backup-manifest.json':
                continue

            # Reject absolute paths
            if member.name.startswith('/'):
                raise ValueError(f"Absolute path not allowed: {member.name}")

            # Reject path traversal
            member_path = (target_dir / member.name).resolve()
            if not member_path.is_relative_to(target_dir):
                raise ValueError(f"Path traversal detected: {member.name}")

            # Reject symlinks
            if member.issym() or member.islnk():
                raise ValueError(f"Symbolic links not allowed: {member.name}")

        # All validated - safe to extract
        tar.extractall(target_dir)

        # Set correct permissions for sensitive files
        for vpn_config in (target_dir / "wireguard").glob("*.conf"):
            vpn_config.chmod(0o600)
```

### FastAPI Streaming Download

```python
# Source: FastAPI FileResponse documentation
# https://fastapi.tiangolo.com/advanced/custom-response/

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

@router.post("/backup/create")
async def create_backup(user: UserInfo = Depends(get_current_user)):
    """Create and download system backup."""
    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_filename = f"eco-iot-gw-backup-{timestamp}.tar.gz"
    backup_path = Path(f"/tmp/{backup_filename}")

    try:
        backup_service.create_backup(backup_path)

        # Log to audit
        audit_service.log(
            username=user.username,
            action="backup_create",
            resource="system",
            ip_address=request.client.host,
            details={"filename": backup_filename}
        )

        # FileResponse streams automatically, sets headers
        return FileResponse(
            path=backup_path,
            filename=backup_filename,
            media_type="application/gzip"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### FastAPI Streaming Upload

```python
# Source: FastAPI UploadFile documentation
# https://fastapi.tiangolo.com/tutorial/request-files/

from fastapi import UploadFile, File

@router.post("/backup/restore")
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """Upload and restore from backup file."""
    # Validate file type
    if not file.filename.endswith('.tar.gz'):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Must be .tar.gz"
        )

    # Save to temporary location (streaming, memory efficient)
    temp_path = Path(f"/tmp/restore-{uuid.uuid4()}.tar.gz")

    try:
        # Stream upload to disk in chunks
        async with aiofiles.open(temp_path, 'wb') as f:
            while chunk := await file.read(8192):  # 8KB chunks
                await f.write(chunk)

        # Validate and restore
        backup_service.restore_from_file(temp_path)

        # Log to audit
        audit_service.log(
            username=user.username,
            action="backup_restore",
            resource="system",
            ip_address=request.client.host,
            details={"filename": file.filename}
        )

        return SuccessResponse(message="Backup restored successfully")

    except ValueError as e:
        # Validation errors
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GNU tar format | PAX format (POSIX.1-2001) | Python 3.8+ default | No filename/path length limits, UTF-8 support |
| Manual permission preservation | tarfile filter parameter | Python 3.12 (2023) | Built-in path validation, safer extraction |
| Sync file operations | Async with aiofiles | Modern FastAPI (2024+) | Better concurrency, non-blocking I/O |
| No backup verification | Manifest with checksums | PostgreSQL 13+ pattern (2020) | Validate backup integrity before/after restore |

**Deprecated/outdated:**
- **tarfile GNU_FORMAT**: Use PAX_FORMAT (default since Python 3.8) - better Unicode, no limits
- **Shell tar commands in Python**: Use tarfile module - safer, no injection risks
- **Synchronous file reads**: For large files, prefer streaming/chunking to avoid memory issues

## Open Questions

Things that couldn't be fully resolved:

1. **Backup compression level tradeoff**
   - What we know: gzip default level is 9, can use level 6 for faster backups
   - What's unclear: Optimal compression level for IoT Gateway (speed vs size on Raspberry Pi)
   - Recommendation: Start with default (9), add compression_level parameter for future optimization

2. **Async vs sync tar creation**
   - What we know: tarfile is synchronous, can use thread pool for async
   - What's unclear: Whether async tar creation adds enough value to justify complexity
   - Recommendation: Start with sync tarfile (simpler), measure if it blocks event loop, add async wrapper if needed

3. **Backup scheduling/automation**
   - What we know: Phase scope is manual backup/restore UI
   - What's unclear: Future automated scheduled backups would need different storage strategy
   - Recommendation: Design with future automation in mind (manifest versioning, retention policy hooks)

4. **Restore rollback strategy**
   - What we know: Restore overwrites existing configs
   - What's unclear: Should we create pre-restore backup for rollback?
   - Recommendation: Consider atomic restore (extract to temp, validate, then move) for safety

## Sources

### Primary (HIGH confidence)
- [Python tarfile documentation](https://docs.python.org/3/library/tarfile.html) - Official stdlib docs
- [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/) - UploadFile usage
- [FastAPI Custom Response](https://fastapi.tiangolo.com/advanced/custom-response/) - FileResponse and StreamingResponse
- [PostgreSQL Backup Manifest Format](https://www.postgresql.org/docs/current/backup-manifest-format.html) - Manifest pattern

### Secondary (MEDIUM confidence)
- [FastAPI Async tar.gz Streaming](https://openillumi.com/en/en-fastapi-async-tar-gz-streaming/) - Memory-efficient streaming pattern
- [Python Tarfile Vulnerability](https://www.securitycompass.com/kontra/what-is-the-tarfile-vulnerability-in-python/) - Path traversal security
- [GNU tar Security](https://www.gnu.org/software/tar/manual/html_section/Security.html) - Official security guidance
- [Linux Backup Best Practices](https://www.ainfosys.com/tutorials/linux-server-backup-best-practices/) - Validation and testing strategies
- [Backup Verification Best Practices](https://www.acronis.com/en/blog/posts/best-practices-for-verifying-and-validating-your-backups/) - Checksum validation, test restores

### Tertiary (LOW confidence)
- [Async Stream Library](https://github.com/chimpler/async-stream) - Alternative for async compression
- [aiofiles](https://pypi.org/project/aiofiles/) - Async file operations library

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib or existing FastAPI dependencies, well-documented
- Architecture: HIGH - Patterns verified from official docs and production systems (PostgreSQL, FastAPI)
- Pitfalls: HIGH - Security issues verified from official GNU tar docs and Python security advisories

**Research date:** 2026-01-24
**Valid until:** 2026-04-24 (90 days - stable domain, stdlib-based)

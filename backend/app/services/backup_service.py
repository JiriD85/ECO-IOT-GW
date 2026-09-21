"""Bounded configuration archives. No operating system, live DB, or identity cloning."""
import asyncio
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ..config import settings
from .audit_service import audit_service


class BackupService:
    MAX_BYTES = 128 * 1024 * 1024
    MAX_FILES = 10000
    # Explicit roots: never accept paths chosen by an uploaded manifest.
    BACKUP_PATHS = [
        Path('/etc/eco-iot-gw'), Path('/etc/openvpn'), Path('/etc/wireguard'),
        Path('/etc/chrony'), Path('/etc/NetworkManager/system-connections'),
        Path('/etc/thingsboard-gateway/config'), Path('/opt/eco/tb-gateway/config'),
        Path('/var/lib/eco-iot-gw/branding'), Path('/var/lib/eco-iot-gw/thingsboard'),
        Path('/var/lib/eco-iot-gw/docker-compose'), Path('/var/lib/eco-iot-gw/vpn'),
        *[Path('/var/lib/eco-iot-gw') / name for name in
          ('modem_config.json', 'sms_config.json', 'watchdog_config.json', 'serial_config.json')],
    ]

    def __init__(self, root=Path('/'), temp_dir=None):
        self.root = Path(root).resolve()
        self.temp_dir = Path(temp_dir or tempfile.gettempdir()) / 'eco-iot-gw-backups'
        self.temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, name):
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name or ':' in name:
            raise ValueError('Invalid archive path')
        allowed = [PurePosixPath(str(p).replace('\\', '/').lstrip('/')) for p in self.BACKUP_PATHS]
        if not any(parts == p or parts.is_relative_to(p) for p in allowed):
            raise ValueError(f'Path is outside configuration roots: {name}')
        path = self.root.joinpath(*parts.parts)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Path leaves restore root')
        for parent in [path, *path.parents]:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ValueError('Symlinks are not supported in configuration backups')
        return path

    def _create(self):
        files = {}
        total = 0
        for configured in self.BACKUP_PATHS:
            name = configured.as_posix().lstrip('/')
            source = self._path(name)
            if not source.exists():
                continue
            for item in ([source] if source.is_file() else sorted(source.rglob('*'))):
                relative = item.relative_to(self.root).as_posix()
                self._path(relative)
                if item.is_dir():
                    continue
                if not item.is_file():
                    raise ValueError('Only regular configuration files can be archived')
                total += item.stat().st_size
                if total > self.MAX_BYTES or len(files) >= self.MAX_FILES:
                    raise ValueError('Configuration backup exceeds size limit')
                data = item.read_bytes()
                files[relative] = (data, item.stat().st_mode & 0o777)
        manifest = {'version': '1.1', 'created_at': datetime.now(timezone.utc).isoformat(),
                    'hostname': __import__('socket').gethostname(), 'app_version': settings.APP_VERSION,
                    'paths': list(files), 'sha256': {n: hashlib.sha256(d).hexdigest() for n, (d, _) in files.items()}}
        destination = self.temp_dir / f'eco-config-{uuid.uuid4().hex}.tar.gz'
        try:
            with destination.open('xb') as stream:
                os.chmod(destination, 0o600)
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    for name, data, mode in [('backup-manifest.json', json.dumps(manifest).encode(), 0o600),
                                              *[(n, d, m) for n, (d, m) in files.items()]]:
                        member = tarfile.TarInfo(name)
                        member.size, member.mode = len(data), mode
                        archive.addfile(member, io.BytesIO(data))
            return {'success': True, 'backup_file': str(destination), 'backup_filename': destination.name,
                    'manifest': manifest, 'size': destination.stat().st_size}
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def _read(self, file_path):
        contents = {}
        total = 0
        with tarfile.open(file_path, 'r:gz') as archive:
            for i, member in enumerate(archive):
                if i > self.MAX_FILES or not (member.isfile() or member.isdir()):
                    raise ValueError('Archive contains unsupported members')
                if member.name != 'backup-manifest.json':
                    self._path(member.name)
                if member.isdir():
                    continue
                total += member.size
                if member.size < 0 or total > self.MAX_BYTES or member.name in contents:
                    raise ValueError('Archive size limit or duplicate member')
                contents[member.name] = (archive.extractfile(member).read(), member.mode & 0o777)
        if 'backup-manifest.json' not in contents:
            raise ValueError('Backup missing manifest')
        manifest = json.loads(contents.pop('backup-manifest.json')[0])
        if manifest.get('version') not in ('1.0', '1.1'):
            raise ValueError('Unsupported backup version')
        if manifest['version'] == '1.1':
            actual = {n: hashlib.sha256(data).hexdigest() for n, (data, _) in contents.items()}
            if manifest.get('sha256') != actual:
                raise ValueError('Backup checksum mismatch')
        return manifest, contents

    async def validate_backup(self, file_path):
        manifest, _ = await asyncio.to_thread(self._read, file_path)
        return manifest

    def _restore(self, file_path):
        manifest, contents = self._read(file_path)  # Validate everything before the first write.
        previous = {}
        try:
            for name, (data, mode) in contents.items():
                destination = self._path(name)
                previous[name] = ((destination.read_bytes(), destination.stat().st_mode & 0o777)
                                  if destination.exists() else None)
                self._replace(destination, data, mode)
        except Exception:
            for name, old in previous.items():
                destination = self._path(name)
                if old is None:
                    destination.unlink(missing_ok=True)
                else:
                    self._replace(destination, *old)
            raise
        return {'success': True, 'message': 'Configuration restored. Reboot to apply it.',
                'restored_paths': list(contents), 'manifest': manifest}

    @staticmethod
    def _replace(destination, data, mode):
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        owner = destination.stat() if destination.exists() else None
        fd, temporary = tempfile.mkstemp(dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                # Atomic replacement must retain access for the existing service
                # account, even when the restore itself runs as root.
                if owner is not None and hasattr(os, 'fchown'):
                    os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
                os.fchmod(stream.fileno(), mode) if hasattr(os, 'fchmod') else None
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)

    async def _operation(self, operation, username, ip_address, *args):
        try:
            result = await asyncio.to_thread(operation, *args)
        except Exception as exc:
            result = {'success': False, 'message': str(exc)}
        audit_service.log(username=username, action='backup_' + operation.__name__.lstrip('_'),
                          resource='system', ip_address=ip_address, success=result['success'])
        return result

    async def create_backup(self, username='system', ip_address='127.0.0.1'):
        return await self._operation(self._create, username, ip_address)

    async def restore_backup(self, file_path, username='system', ip_address='127.0.0.1'):
        return await self._operation(self._restore, username, ip_address, file_path)


backup_service = BackupService()

"""
ECO-IOT-GW Docker Service
Docker SDK integration for container management
"""
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import docker
from docker.errors import DockerException, NotFound

from ..config import settings
from ..models.schemas import ContainerInfo

logger = logging.getLogger(__name__)


class DockerService:
    """Service for Docker and Docker Compose operations."""

    def __init__(self):
        self._client: Optional[docker.DockerClient] = None

    @property
    def client(self) -> docker.DockerClient:
        """Get Docker client, creating if necessary."""
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as e:
                logger.error(f"Failed to connect to Docker: {e}")
                raise RuntimeError("Docker is not available")
        return self._client

    def get_containers(self, all_containers: bool = True) -> List[ContainerInfo]:
        """
        Get list of all containers.

        Args:
            all_containers: Include stopped containers

        Returns:
            List of ContainerInfo objects
        """
        try:
            containers = self.client.containers.list(all=all_containers)
            result = []

            for container in containers:
                # Get port mappings
                ports = {}
                for port, bindings in (container.ports or {}).items():
                    if bindings:
                        ports[port] = [b.get('HostPort') for b in bindings]

                result.append(ContainerInfo(
                    id=container.short_id,
                    name=container.name,
                    image=container.image.tags[0] if container.image.tags else container.image.short_id,
                    status=container.status,
                    state=container.attrs['State']['Status'],
                    created=datetime.fromisoformat(
                        container.attrs['Created'].replace('Z', '+00:00')
                    ),
                    ports=ports
                ))

            return result

        except DockerException as e:
            logger.error(f"Failed to list containers: {e}")
            return []

    def is_compose_running(self) -> bool:
        """Check if compose containers are running."""
        try:
            containers = self.get_containers()
            # Check for containers with compose labels
            for container in containers:
                if container.status == "running":
                    return True
            return False
        except Exception:
            return False

    def compose_up(self, detach: bool = True) -> bool:
        """
        Run docker-compose up.

        Args:
            detach: Run in detached mode

        Returns:
            True if successful
        """
        compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

        if not compose_file.exists():
            raise FileNotFoundError("docker-compose.yml not found")

        cmd = ["docker", "compose", "-f", str(compose_file), "up"]
        if detach:
            cmd.append("-d")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(settings.DOCKER_COMPOSE_DIR)
            )

            if result.returncode != 0:
                logger.error(f"docker-compose up failed: {result.stderr}")
                raise RuntimeError(f"docker-compose up failed: {result.stderr}")

            logger.info("docker-compose up completed successfully")
            return True

        except subprocess.TimeoutExpired:
            raise RuntimeError("docker-compose up timed out")

    def compose_down(self, remove_volumes: bool = False) -> bool:
        """
        Run docker-compose down.

        Args:
            remove_volumes: Also remove volumes

        Returns:
            True if successful
        """
        compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

        cmd = ["docker", "compose", "-f", str(compose_file), "down"]
        if remove_volumes:
            cmd.append("-v")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(settings.DOCKER_COMPOSE_DIR)
            )

            if result.returncode != 0:
                logger.error(f"docker-compose down failed: {result.stderr}")
                raise RuntimeError(f"docker-compose down failed: {result.stderr}")

            logger.info("docker-compose down completed successfully")
            return True

        except subprocess.TimeoutExpired:
            raise RuntimeError("docker-compose down timed out")

    def get_container_logs(
        self,
        container_name: str,
        lines: int = 100,
        timestamps: bool = True
    ) -> str:
        """
        Get logs from a container.

        Args:
            container_name: Name of the container
            lines: Number of log lines
            timestamps: Include timestamps

        Returns:
            Log output as string
        """
        try:
            container = self.client.containers.get(container_name)
            logs = container.logs(
                tail=lines,
                timestamps=timestamps
            )
            return logs.decode('utf-8', errors='replace')

        except NotFound:
            raise ValueError(f"Container {container_name} not found")
        except DockerException as e:
            raise RuntimeError(f"Failed to get logs: {e}")

    def start_container(self, container_name: str) -> bool:
        """Start a container."""
        try:
            container = self.client.containers.get(container_name)
            container.start()
            logger.info(f"Container {container_name} started")
            return True
        except NotFound:
            raise ValueError(f"Container {container_name} not found")
        except DockerException as e:
            raise RuntimeError(f"Failed to start container: {e}")

    def stop_container(self, container_name: str, timeout: int = 10) -> bool:
        """Stop a container."""
        try:
            container = self.client.containers.get(container_name)
            container.stop(timeout=timeout)
            logger.info(f"Container {container_name} stopped")
            return True
        except NotFound:
            raise ValueError(f"Container {container_name} not found")
        except DockerException as e:
            raise RuntimeError(f"Failed to stop container: {e}")

    def restart_container(self, container_name: str, timeout: int = 10) -> bool:
        """Restart a container."""
        try:
            container = self.client.containers.get(container_name)
            container.restart(timeout=timeout)
            logger.info(f"Container {container_name} restarted")
            return True
        except NotFound:
            raise ValueError(f"Container {container_name} not found")
        except DockerException as e:
            raise RuntimeError(f"Failed to restart container: {e}")

    def pull_image(self, image: str) -> bool:
        """Pull a Docker image."""
        try:
            self.client.images.pull(image)
            logger.info(f"Image {image} pulled")
            return True
        except DockerException as e:
            raise RuntimeError(f"Failed to pull image: {e}")


# Global docker service instance
docker_service = DockerService()

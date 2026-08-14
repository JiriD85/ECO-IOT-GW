"""
ECO-IOT-GW Docker API
Docker-Compose management endpoints
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status

from ..config import settings
from ..models.schemas import (
    ContainerInfo,
    DockerComposeRequest,
    DockerComposeResponse,
    DockerStatusResponse,
    ErrorResponse,
    SuccessResponse,
    UserInfo
)
from ..security.auth import get_current_user
from ..security.validators import validate_docker_compose
from ..services.docker_service import docker_service

logger = logging.getLogger(__name__)
router = APIRouter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip


def log_audit(username: str, action: str, ip: str, details: dict = None, success: bool = True):
    """Log audit event."""
    try:
        from ..services.audit_service import audit_service
        audit_service.log(
            username=username,
            action=action,
            resource="docker",
            ip_address=ip,
            success=success,
            details=details
        )
    except Exception as e:
        logger.warning(f"Failed to log audit: {e}")


@router.get(
    "/compose",
    response_model=DockerComposeResponse,
    responses={404: {"model": ErrorResponse}}
)
async def get_compose(user: UserInfo = Depends(get_current_user)):
    """
    Get current docker-compose.yml content.

    Returns the content of the currently configured docker-compose file.
    """
    compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

    if not compose_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No docker-compose.yml configured"
        )

    content = compose_file.read_text()
    mtime = datetime.fromtimestamp(compose_file.stat().st_mtime)

    return DockerComposeResponse(
        filename="docker-compose.yml",
        content=content,
        last_modified=mtime
    )


@router.post(
    "/compose",
    response_model=SuccessResponse,
    responses={400: {"model": ErrorResponse}}
)
async def upload_compose(
    request: Request,
    data: DockerComposeRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload docker-compose.yml content.

    - **content**: YAML content of the docker-compose file
    - **filename**: Optional filename (defaults to docker-compose.yml)

    The content is validated before saving.
    """
    client_ip = get_client_ip(request)

    # Validate content
    try:
        validate_docker_compose(data.content)
    except HTTPException:
        log_audit(user.username, "upload_compose", client_ip,
                 {"error": "validation_failed"}, success=False)
        raise

    # Ensure directory exists
    settings.DOCKER_COMPOSE_DIR.mkdir(parents=True, exist_ok=True)

    # Save file
    compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"
    compose_file.write_text(data.content)

    log_audit(user.username, "upload_compose", client_ip,
             {"filename": data.filename})

    logger.info(f"Docker compose uploaded by {user.username}")
    return SuccessResponse(message="docker-compose.yml uploaded successfully")


@router.post(
    "/compose/upload",
    response_model=SuccessResponse,
    responses={400: {"model": ErrorResponse}}
)
async def upload_compose_file(
    request: Request,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload docker-compose.yml as a file (for drag & drop).

    Accepts file upload via multipart/form-data.
    """
    client_ip = get_client_ip(request)

    # Check filename
    if not file.filename.endswith(('.yml', '.yaml')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a YAML file (.yml or .yaml)"
        )

    # Read content
    content = await file.read()
    try:
        content_str = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be valid UTF-8"
        )

    # Validate content
    try:
        validate_docker_compose(content_str)
    except HTTPException:
        log_audit(user.username, "upload_compose_file", client_ip,
                 {"filename": file.filename, "error": "validation_failed"}, success=False)
        raise

    # Ensure directory exists
    settings.DOCKER_COMPOSE_DIR.mkdir(parents=True, exist_ok=True)

    # Save file
    compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"
    compose_file.write_text(content_str)

    log_audit(user.username, "upload_compose_file", client_ip,
             {"filename": file.filename})

    logger.info(f"Docker compose file uploaded by {user.username}")
    return SuccessResponse(message="docker-compose.yml uploaded successfully")


@router.delete(
    "/compose",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}}
)
async def delete_compose(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Delete docker-compose.yml.

    Warning: This will remove the docker-compose configuration.
    """
    client_ip = get_client_ip(request)
    compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

    if not compose_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No docker-compose.yml to delete"
        )

    compose_file.unlink()

    log_audit(user.username, "delete_compose", client_ip)

    logger.info(f"Docker compose deleted by {user.username}")
    return SuccessResponse(message="docker-compose.yml deleted successfully")


@router.get(
    "/status",
    response_model=DockerStatusResponse
)
async def get_status(user: UserInfo = Depends(get_current_user)):
    """
    Get Docker status and container information.

    Returns list of containers and their current status.
    """
    containers = docker_service.get_containers()
    compose_running = docker_service.is_compose_running()

    return DockerStatusResponse(
        containers=containers,
        compose_running=compose_running
    )


@router.post(
    "/up",
    response_model=SuccessResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}
)
async def compose_up(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Start containers with docker-compose up -d.

    Requires docker-compose.yml to be uploaded first.
    """
    client_ip = get_client_ip(request)
    compose_file = settings.DOCKER_COMPOSE_DIR / "docker-compose.yml"

    if not compose_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No docker-compose.yml configured. Upload one first."
        )

    try:
        docker_service.compose_up()
        log_audit(user.username, "compose_up", client_ip)
        logger.info(f"Docker compose up executed by {user.username}")
        return SuccessResponse(message="Containers started successfully")

    except Exception as e:
        log_audit(user.username, "compose_up", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start containers: {str(e)}"
        )


@router.post(
    "/down",
    response_model=SuccessResponse
)
async def compose_down(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Stop and remove containers with docker-compose down.
    """
    client_ip = get_client_ip(request)

    try:
        docker_service.compose_down()
        log_audit(user.username, "compose_down", client_ip)
        logger.info(f"Docker compose down executed by {user.username}")
        return SuccessResponse(message="Containers stopped successfully")

    except Exception as e:
        log_audit(user.username, "compose_down", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop containers: {str(e)}"
        )


@router.post(
    "/restart",
    response_model=SuccessResponse
)
async def compose_restart(
    request: Request,
    user: UserInfo = Depends(get_current_user)
):
    """
    Restart containers (down + up).
    """
    client_ip = get_client_ip(request)

    try:
        docker_service.compose_down()
        docker_service.compose_up()
        log_audit(user.username, "compose_restart", client_ip)
        logger.info(f"Docker compose restart executed by {user.username}")
        return SuccessResponse(message="Containers restarted successfully")

    except Exception as e:
        log_audit(user.username, "compose_restart", client_ip,
                 {"error": str(e)}, success=False)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart containers: {str(e)}"
        )


@router.get(
    "/logs/{container_name}",
    responses={404: {"model": ErrorResponse}}
)
async def get_container_logs(
    container_name: str,
    lines: int = 100,
    user: UserInfo = Depends(get_current_user)
):
    """
    Get logs from a specific container.

    - **container_name**: Name of the container
    - **lines**: Number of log lines to return (default 100)
    """
    try:
        logs = docker_service.get_container_logs(container_name, lines)
        return {"container": container_name, "logs": logs}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Container not found or error: {str(e)}"
        )


@router.post(
    "/container/{container_name}/start",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}}
)
async def start_container(
    request: Request,
    container_name: str,
    user: UserInfo = Depends(get_current_user)
):
    """Start a specific container."""
    client_ip = get_client_ip(request)

    try:
        docker_service.start_container(container_name)
        log_audit(user.username, "start_container", client_ip,
                 {"container": container_name})
        return SuccessResponse(message=f"Container {container_name} started")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/container/{container_name}/stop",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}}
)
async def stop_container(
    request: Request,
    container_name: str,
    user: UserInfo = Depends(get_current_user)
):
    """Stop a specific container."""
    client_ip = get_client_ip(request)

    try:
        docker_service.stop_container(container_name)
        log_audit(user.username, "stop_container", client_ip,
                 {"container": container_name})
        return SuccessResponse(message=f"Container {container_name} stopped")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/container/{container_name}/restart",
    response_model=SuccessResponse,
    responses={404: {"model": ErrorResponse}}
)
async def restart_container(
    request: Request,
    container_name: str,
    user: UserInfo = Depends(get_current_user)
):
    """Restart a specific container."""
    client_ip = get_client_ip(request)

    try:
        docker_service.restart_container(container_name)
        log_audit(user.username, "restart_container", client_ip,
                 {"container": container_name})
        return SuccessResponse(message=f"Container {container_name} restarted")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

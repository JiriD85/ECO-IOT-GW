"""Authenticated local configuration, never a second Modbus master."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from ..config import settings
from ..security.auth import get_current_user
from ..services.modbus_config import ModbusConfig
from .serial import log_audit, get_client_ip

router = APIRouter()


class Change(BaseModel):
    revision: str
    slaves: list[dict] = Field(default_factory=list, max_length=64)


@router.get('/config')
def configuration(user=Depends(get_current_user)):
    try:
        return ModbusConfig(settings.TB_GATEWAY_CONFIG_DIR).list()
    except (OSError, ValueError, KeyError) as e:
        raise HTTPException(503, 'Active connector configuration unavailable') from e


def apply_change(name, body, request, user, restore=False):
    try:
        result = ModbusConfig(settings.TB_GATEWAY_CONFIG_DIR).save(name, body.revision, body.slaves, restore)
        log_audit(user.username, 'modbus.restore' if restore else 'modbus.override', get_client_ip(request), {'connector': name})
        return result
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    except OSError as e:
        raise HTTPException(503, 'Could not write connector configuration') from e


@router.put('/config/{name}')
def update(name: str, body: Change, request: Request, user=Depends(get_current_user)):
    return apply_change(name, body, request, user)


@router.post('/config/{name}/restore')
def restore(name: str, body: Change, request: Request, user=Depends(get_current_user)):
    return apply_change(name, body, request, user, True)

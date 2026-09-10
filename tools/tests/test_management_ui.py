"""Management API behavior without contacting hardware."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))


def test_unimplemented_poll_does_not_claim_success():
    from app.api.diagnostics import poll_modbus_register
    with pytest.raises(HTTPException) as result:
        asyncio.run(poll_modbus_register(device='PF1', register=1, user=None))
    assert result.value.status_code == 501

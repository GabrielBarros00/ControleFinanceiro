import pytest
import json
from fastapi import Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from app.api.errors import (
    internal_server_error_handler,
    validation_exception_handler,
    http_exception_handler
)
import unittest.mock

@pytest.mark.asyncio
async def test_internal_server_error_handler():
    mock_request = unittest.mock.MagicMock(spec=Request)
    exc = Exception("Crash")
    response = await internal_server_error_handler(mock_request, exc)
    assert response.status_code == 500
    data = json.loads(response.body)
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"

@pytest.mark.asyncio
async def test_validation_exception_handler():
    mock_request = unittest.mock.MagicMock(spec=Request)
    # Mocking what Pydantic/FastAPI sends to the handler
    exc = RequestValidationError(errors=[{
        "loc": ["body", "email"],
        "msg": "invalid email",
        "type": "value_error"
    }])
    response = await validation_exception_handler(mock_request, exc)
    assert response.status_code == 422
    data = json.loads(response.body)
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "email" in data["error"]["details"]

@pytest.mark.asyncio
async def test_http_exception_handler():
    mock_request = unittest.mock.MagicMock(spec=Request)
    exc = StarletteHTTPException(status_code=404, detail="Resource not found")
    response = await http_exception_handler(mock_request, exc)
    assert response.status_code == 404
    data = json.loads(response.body)
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["message"] == "Resource not found"

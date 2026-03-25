import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_API_KEY

HEADERS = {"X-API-Key": TEST_API_KEY}


def _make_upload_response(**kwargs):
    from app.knowledge_base.schemas import KnowledgeBaseUploadResponse

    defaults = {
        "knowledge_base_id": "sc-1",
        "document_id": "doc-1",
        "chunk_count": 5,
        "status": "processed",
    }
    defaults.update(kwargs)
    return KnowledgeBaseUploadResponse(**defaults)


# --- POST /scorecards/{id}/knowledge-base/upload ---


async def test_upload_returns_200(async_client: AsyncClient):
    with patch("app.knowledge_base.router.process_document", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = _make_upload_response()

        response = await async_client.post(
            "/api/v1/scorecards/sc-1/knowledge-base/upload",
            files={"file": ("test.txt", b"Hello world content here", "text/plain")},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["knowledge_base_id"] == "sc-1"
    assert data["document_id"] == "doc-1"
    assert data["chunk_count"] == 5
    assert data["status"] == "processed"


async def test_upload_with_document_id(async_client: AsyncClient):
    with patch("app.knowledge_base.router.process_document", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = _make_upload_response(status="replaced")

        response = await async_client.post(
            "/api/v1/scorecards/sc-1/knowledge-base/upload?document_id=existing-doc",
            files={"file": ("test.pdf", b"%PDF-fake", "application/pdf")},
            headers=HEADERS,
        )

    assert response.status_code == 200
    mock_process.assert_called_once()
    call_kwargs = mock_process.call_args[1]
    assert call_kwargs["document_id"] == "existing-doc"


async def test_upload_returns_401_without_api_key(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/scorecards/sc-1/knowledge-base/upload",
        files={"file": ("test.txt", b"content", "text/plain")},
    )
    assert response.status_code == 401


async def test_upload_rejects_unsupported_format(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/scorecards/sc-1/knowledge-base/upload",
        files={"file": ("test.exe", b"binary content", "application/octet-stream")},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_upload_rejects_empty_file(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/scorecards/sc-1/knowledge-base/upload",
        files={"file": ("test.txt", b"", "text/plain")},
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_upload_rejects_oversized_file(async_client: AsyncClient):
    large_content = b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1 byte
    response = await async_client.post(
        "/api/v1/scorecards/sc-1/knowledge-base/upload",
        files={"file": ("test.txt", large_content, "text/plain")},
        headers=HEADERS,
    )
    assert response.status_code == 422


# --- POST /scorecards/{id}/knowledge-base/query ---


async def test_query_returns_200(async_client: AsyncClient):
    from app.knowledge_base.schemas import KBQueryResponse

    with patch("app.knowledge_base.router.query_knowledge_base", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = KBQueryResponse(knowledge_base_id="sc-1", results=[])

        response = await async_client.post(
            "/api/v1/scorecards/sc-1/knowledge-base/query",
            json={"query": "test query"},
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["knowledge_base_id"] == "sc-1"
    assert data["results"] == []


async def test_query_returns_401_without_api_key(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/scorecards/sc-1/knowledge-base/query",
        json={"query": "test"},
    )
    assert response.status_code == 401


# --- DELETE /scorecards/{id}/knowledge-base ---


async def test_delete_returns_200(async_client: AsyncClient):
    with patch("app.knowledge_base.router.delete_knowledge_base", new_callable=AsyncMock):
        response = await async_client.delete(
            "/api/v1/scorecards/sc-1/knowledge-base",
            headers=HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["knowledge_base_id"] == "sc-1"


async def test_delete_returns_401_without_api_key(async_client: AsyncClient):
    response = await async_client.delete(
        "/api/v1/scorecards/sc-1/knowledge-base",
    )
    assert response.status_code == 401

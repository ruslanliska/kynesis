import asyncio
import uuid

import logfire
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import AsyncOpenAI
from pinecone.exceptions import NotFoundException

from app.core.ai_provider import get_pinecone_client, get_pinecone_index_name
from app.core.config import get_settings
from app.knowledge_base.parsers import extract_text
from app.knowledge_base.schemas import (
    KBQueryResponse,
    KBQueryResult,
    KnowledgeBaseUploadResponse,
)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 80
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
UPSERT_BATCH_SIZE = 100


def _get_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


async def _generate_embeddings(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    with logfire.span("generate_embeddings", chunk_count=len(texts)):
        response = await client.embeddings.create(
            input=texts,
            model=EMBEDDING_MODEL,
        )
        return [item.embedding for item in response.data]


def _get_pinecone_index():
    pc = get_pinecone_client()
    return pc.Index(get_pinecone_index_name())


async def process_document(
    filename: str,
    content: bytes,
    knowledge_base_id: str | None = None,
    document_id: str | None = None,
) -> KnowledgeBaseUploadResponse:
    kb_id = knowledge_base_id or str(uuid.uuid4())
    doc_id = document_id or str(uuid.uuid4())
    is_replacement = document_id is not None

    with logfire.span(
        "process_document",
        knowledge_base_id=kb_id,
        document_id=doc_id,
        filename=filename,
    ):
        # If replacing, delete old chunks first
        if is_replacement:
            await delete_document(kb_id, doc_id)

        # Parse document
        text = extract_text(filename, content)
        if not text.strip():
            raise ValueError("Document contains no extractable text.")

        # Chunk
        splitter = _get_text_splitter()
        chunks = splitter.split_text(text)

        if not chunks:
            raise ValueError("Document produced no chunks after splitting.")

        # Generate embeddings
        embeddings = await _generate_embeddings(chunks)

        # Build vectors with metadata
        vectors = [
            {
                "id": f"{doc_id}-{i}",
                "values": emb,
                "metadata": {
                    "knowledge_base_id": kb_id,
                    "document_id": doc_id,
                    "chunk_index": i,
                    "text": chunk,
                    "source_filename": filename,
                },
            }
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]

        # Upsert to Pinecone in batches
        index = _get_pinecone_index()
        with logfire.span("pinecone_upsert", vector_count=len(vectors)):
            for batch_start in range(0, len(vectors), UPSERT_BATCH_SIZE):
                batch = vectors[batch_start : batch_start + UPSERT_BATCH_SIZE]
                await asyncio.to_thread(
                    index.upsert, vectors=batch, namespace=kb_id
                )

        return KnowledgeBaseUploadResponse(
            knowledge_base_id=kb_id,
            document_id=doc_id,
            chunk_count=len(chunks),
            status="replaced" if is_replacement else "processed",
        )


async def query_knowledge_base(
    knowledge_base_id: str,
    query: str,
    top_k: int = 5,
) -> KBQueryResponse:
    with logfire.span(
        "query_knowledge_base",
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
    ):
        # Generate query embedding
        embeddings = await _generate_embeddings([query])
        query_embedding = embeddings[0]

        # Query Pinecone
        index = _get_pinecone_index()
        try:
            results = await asyncio.to_thread(
                index.query,
                vector=query_embedding,
                top_k=top_k,
                namespace=knowledge_base_id,
                include_metadata=True,
            )
        except NotFoundException:
            return KBQueryResponse(knowledge_base_id=knowledge_base_id, results=[])

        matches = results.get("matches", [])
        query_results = [
            KBQueryResult(
                text=match["metadata"]["text"],
                score=match["score"],
                document_id=match["metadata"]["document_id"],
                source_filename=match["metadata"]["source_filename"],
                chunk_index=match["metadata"]["chunk_index"],
            )
            for match in matches
        ]

        return KBQueryResponse(
            knowledge_base_id=knowledge_base_id,
            results=query_results,
        )


async def get_rag_context(
    knowledge_base_id: str,
    query: str,
    top_k: int = 5,
) -> str | None:
    """Retrieve relevant chunks as a single context string for assessment RAG."""
    try:
        response = await query_knowledge_base(knowledge_base_id, query, top_k)
        if not response.results:
            return None
        return "\n\n---\n\n".join(r.text for r in response.results)
    except Exception as e:
        logfire.warn("Knowledge base retrieval failed", error=str(e))
        return None


async def delete_document(knowledge_base_id: str, document_id: str) -> None:
    index = _get_pinecone_index()
    with logfire.span(
        "delete_document",
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
    ):
        try:
            await asyncio.to_thread(
                index.delete,
                filter={"document_id": {"$eq": document_id}},
                namespace=knowledge_base_id,
            )
        except NotFoundException:
            pass  # Namespace doesn't exist yet, nothing to delete


async def delete_knowledge_base(knowledge_base_id: str) -> None:
    index = _get_pinecone_index()
    with logfire.span("delete_knowledge_base", knowledge_base_id=knowledge_base_id):
        try:
            await asyncio.to_thread(
                index.delete,
                delete_all=True,
                namespace=knowledge_base_id,
            )
        except NotFoundException:
            pass  # Namespace doesn't exist, nothing to delete

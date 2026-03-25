import logfire
from openai import AsyncOpenAI

from app.core.config import get_settings

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25MB (OpenAI Whisper limit)


async def transcribe_audio(filename: str, content: bytes) -> str:
    """Transcribe audio file using OpenAI Whisper API."""
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    with logfire.span("transcribe_audio", filename=filename, size_bytes=len(content)):
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, content),
            response_format="text",
        )
        return response.strip()

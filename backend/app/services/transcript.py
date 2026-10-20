# services/transcript.py
import subprocess
import os
import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from config import settings

async def fetch_robust_transcript(video_id: str) -> list[dict]:
    # Tier 1: Try Official YouTube Captions API
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        if transcript:
            return transcript
    except Exception:
        pass

    # Tier 2: Fallback to yt-dlp Audio Download + Whisper Speech-to-Text API
    try:
        audio_path = f"/tmp/{video_id}.mp3"
        ydl_cmd = [
            "yt-dlp", "-x", "--audio-format", "mp3",
            "-o", audio_path,
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        subprocess.run(ydl_cmd, check=True, capture_output=True)

        # Transcribe audio via OpenAI Whisper or Groq Whisper API
        async with httpx.AsyncClient() as client:
            with open(audio_path, "rb") as f:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    files={"file": (f"{video_id}.mp3", f, "audio/mp3")},
                    data={"model": "whisper-1", "response_format": "verbose_json"}
                )
        
        if os.path.exists(audio_path):
            os.remove(audio_path)

        data = response.json()
        segments = [
            {"text": seg["text"], "start": seg["start"], "duration": seg["end"] - seg["start"]}
            for seg in data.get("segments", [])
        ]
        return segments
    except Exception as e:
        raise Exception(f"All transcript recovery methods failed: {str(e)}")
#!/usr/bin/env python3
"""
Sarvam voice proxy — STT and TTS endpoints.

The API key lives in SARVAM_API_KEY (env var only, never in frontend code).
The frontend calls these proxy endpoints; they forward to Sarvam.

For real-time feel:
- TTS splits AI responses into sentences and synthesizes each independently
  so the frontend can start playing the first sentence while later ones
  are still being generated (streaming pipeline).
"""
import json
import os
from fastapi import HTTPException, UploadFile, File
from fastapi.responses import Response
import httpx

SARVAM_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


def check_sarvam():
    if not SARVAM_KEY:
        raise HTTPException(503, "SARVAM_API_KEY not configured")


async def stt_proxy(audio: UploadFile = File(...), language: str = "hi-IN"):
    """Proxy speech-to-text through Sarvam (saarika model)."""
    check_sarvam()
    content = await audio.read()
    if not content:
        raise HTTPException(400, "empty audio")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            SARVAM_STT_URL,
            headers={"Authorization": f"Bearer {SARVAM_KEY}"},
            files={"file": ("audio.wav", content, "audio/wav")},
            data={"model": "saarika:v2.5", "language_code": language},
        )
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"Sarvam STT error: {r.text[:200]}")
    result = r.json()
    return {"transcript": result.get("transcript", ""),
            "language": result.get("language_code", language)}


async def tts_proxy(text: str, voice: str = "priya",
                    language: str = "hi-IN", speed: float = 1.0):
    """Proxy text-to-speech through Sarvam (bulbul model).
    Returns WAV audio bytes."""
    check_sarvam()
    if not text.strip():
        raise HTTPException(400, "empty text")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            SARVAM_TTS_URL,
            headers={"Authorization": f"Bearer {SARVAM_KEY}",
                     "Content-Type": "application/json"},
            json={"text": text[:2400],  # Sarvam limit per request
                  "model": "bulbul:v3",
                  "speaker": voice,
                  "language_code": language,
                  "speech_rate": speed,
                  "audio_format": "wav"},
        )
    if r.status_code != 200:
        raise HTTPException(r.status_code, f"Sarvam TTS error: {r.text[:200]}")
    audio_b64 = r.json().get("audios", [None])[0]
    if not audio_b64:
        raise HTTPException(500, "no audio in Sarvam response")
    import base64
    return Response(content=base64.b64decode(audio_b64),
                    media_type="audio/wav")


def split_for_tts(text: str, max_chars: int = 2400):
    """Split AI response into sentence chunks for streaming TTS.
    Returns list of (sentence, lang_hint)."""
    import re
    # detect Hindi vs English per sentence (rough heuristic)
    sentences = re.split(r'(?<=[.!?।])\s+', text.strip())
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip()
    if current:
        chunks.append(current.strip())
    return chunks if chunks else [text]


def detect_language(text: str) -> str:
    """Rough language detection for TTS voice selection."""
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    if devanagari > len(text) * 0.3:
        return "hi-IN"
    return "en-IN"

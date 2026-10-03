#!/usr/bin/env python3
"""Simple Sarvam STT/TTS test server. Run: python3 server.py"""
import base64
import os
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, Response
import httpx
import uvicorn

API_KEY = os.environ.get("SARVAM_API_KEY", "sk_gnxdvhkm_Cd0K9pFyM32NeRMOWETty2wG")
STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

app = FastAPI()

@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), language: str = "unknown"):
    """Proxy to Sarvam STT — correct auth header + model name."""
    content = await audio.read()
    print(f"STT: got {len(content)} bytes of audio")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            STT_URL,
            headers={"api-subscription-key": API_KEY},
            files={"file": ("audio.webm", content, "audio/webm")},
            data={"model": "saaras:v4", "language_code": language})
    print(f"STT response: {r.status_code}")
    if r.status_code != 200:
        return {"error": r.text[:300]}
    return r.json()

@app.get("/api/tts")
async def tts(text: str, lang: str = "hi-IN"):
    """Proxy to Sarvam TTS — correct auth + model + speaker."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TTS_URL,
            headers={"api-subscription-key": API_KEY,
                     "Content-Type": "application/json"},
            json={"text": text, "model": "bulbul:v3", "speaker": "priya",
                  "language_code": lang, "output_audio_codec": "wav"})
    print(f"TTS response: {r.status_code}")
    if r.status_code != 200:
        return {"error": r.text[:300]}
    audio_b64 = r.json().get("audios", [None])[0]
    if not audio_b64:
        return {"error": "no audio"}
    return Response(content=base64.b64decode(audio_b64),
                    media_type="audio/wav")

@app.get("/")
def index():
    with open("test.html") as f:
        return HTMLResponse(f.read())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)

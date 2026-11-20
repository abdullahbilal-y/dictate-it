"""Groq-hosted Whisper (large-v3) speech-to-text, with local fallback handled by the engine.

Free tier (Nov 2026): 20 requests/min, 2,000/day, 8h of audio/day per Whisper model. The engine only uploads
audio that local Silero VAD says contains speech: Whisper invents text ("Thank you.") on silence, and it saves
quota. Audio is trimmed to the speech and sent as 16 kHz mono WAV."""
import io
import re
import time
import wave

import numpy as np
import requests

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

HALLUCINATION_PATTERNS = [
    r"^\[.*\]$", r"^\(.*\)$", r"^thank you\.?$", r"^thanks for watching\.?$", r"^subtitles by.*$",
    r"^subscribe\.?$", r"^you\.?$", r"^bye\.?$",
]


def speech_span(audio: np.ndarray, samplerate: int = 16000):
    """(start, end) sample indices of detected speech with a little padding, or None if there's no speech."""
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    stamps = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, speech_pad_ms=200))
    if not stamps:
        return None
    pad = int(0.15 * samplerate)
    return max(0, stamps[0]["start"] - pad), min(len(audio), stamps[-1]["end"] + pad)


def to_wav_bytes(audio: np.ndarray, samplerate: int = 16000) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def clean_segments(segments, prompt: str = "") -> str:
    texts = []
    for seg in segments:
        if float(seg.get("no_speech_prob", 0.0)) > 0.65:
            continue
        text = (seg.get("text") or "").strip()
        if not text or any(re.match(p, text.lower()) for p in HALLUCINATION_PATTERNS):
            continue
        texts.append(text)
    out = " ".join(texts).strip()
    # A known Whisper failure: echoing the vocabulary prompt back when it hears little.
    if prompt and out and out.lower().strip(" .") in prompt.lower():
        return ""
    return out


class GroqTranscriber:
    def __init__(self, api_key: str, model: str = "whisper-large-v3", timeout_s: float = 8.0):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.enabled = bool(api_key)
        self._cooldown_until = 0.0

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key) and time.time() >= self._cooldown_until

    def transcribe(self, audio: np.ndarray, samplerate: int = 16000, language: str = "en", prompt: str = "") -> str:
        """Raises on any failure so the engine can fall back to local Whisper."""
        data = {"model": self.model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt[:800]   # Whisper reads ~224 tokens of prompt
        files = {"file": ("speech.wav", to_wav_bytes(audio, samplerate), "audio/wav")}
        resp = requests.post(API_URL, headers={"Authorization": f"Bearer {self.api_key}"}, data=data, files=files,
                             timeout=self.timeout_s)
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "30") or 30)
            self._cooldown_until = time.time() + min(wait, 300)
            raise RuntimeError(f"Groq STT rate limited (retry in {wait:.0f}s)")
        if resp.status_code in (401, 403):
            self.enabled = False
            raise RuntimeError(f"Groq rejected the key (HTTP {resp.status_code}); using local Whisper from now on")
        if resp.status_code >= 400:
            raise RuntimeError(f"Groq STT HTTP {resp.status_code}: {resp.text[:160]}")
        body = resp.json()
        segments = body.get("segments")
        if segments is None:
            return clean_segments([{"text": body.get("text", "")}], prompt)
        return clean_segments(segments, prompt)

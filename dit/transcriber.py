import os
import re
import numpy as np
from faster_whisper import WhisperModel
import ctranslate2

HALLUCINATION_PATTERNS = [
    r"^\[.*\]$",
    r"^\(.*\)$",
    r"^thank you\.?$",
    r"^thanks for watching\.?$",
    r"^subtitles by\.?$",
    r"^subscribe\.?$",
    r"^you$"
]

class Transcriber:
    def __init__(self, model_name: str = "small", device: str = "auto", compute_type: str = "auto"):
        self.model_name = model_name
        self.device, self.compute_type = self._resolve_device(device, compute_type)
        print(f"[Transcriber] Loading Whisper '{model_name}' on {self.device} ({self.compute_type})...")
        try:
            self.model = WhisperModel(
                model_size_or_path=self.model_name,
                device=self.device,
                compute_type=self.compute_type
            )
            print(f"[Transcriber] Whisper '{model_name}' ready on {self.device}!")
        except Exception as e:
            if self.device == "cuda":
                print(f"[Transcriber] CUDA init failed ({e}), falling back to CPU (int8)...")
                self.device = "cpu"
                self.compute_type = "int8"
                self.model = WhisperModel(
                    model_size_or_path=self.model_name,
                    device=self.device,
                    compute_type=self.compute_type
                )
                print(f"[Transcriber] Whisper '{model_name}' ready on CPU!")
            else:
                raise

    def _resolve_device(self, device: str, compute_type: str):
        if device == "auto":
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
                device = "cuda" if cuda_count > 0 else "cpu"
            except Exception:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        return device, compute_type

    def transcribe(self, audio: np.ndarray, language: str = "en", beam_size: int = 1) -> str:
        """Transcribe 16kHz float32 audio array and return cleaned text."""
        if audio is None or len(audio) == 0:
            return ""

        # Run transcription with VAD filter enabled
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
            condition_on_previous_text=False
        )

        texts = []
        for segment in segments:
            # Check speech confidence
            if segment.no_speech_prob > 0.65:
                continue
            seg_text = segment.text.strip()
            if not seg_text:
                continue
            
            # Hallucination suppression
            lowered = seg_text.lower()
            if any(re.match(pat, lowered) for pat in HALLUCINATION_PATTERNS):
                continue
                
            texts.append(seg_text)

        full_text = " ".join(texts).strip()
        return full_text

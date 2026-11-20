"""STT accuracy bench: synthesise task phrases with Windows SAPI TTS, transcribe them with each engine setup,
and report word error rate. Synthetic voices are cleaner than a real mic, so treat results as relative.

    python tools/stt_bench.py            # local small: no hints vs vocabulary hints + beam 5
    python tools/stt_bench.py --groq     # also Groq whisper-large-v3 (needs GROQ_API_KEY)
"""
import argparse
import os
import re
import sys
import tempfile
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Phrases from real use (2026-11-18 log), with the words Whisper got wrong.
PHRASES = [
    "DP World EIRs are checked and done",
    "Inform Alpha about DPW and GGEA",
    "Port Jebel Ali is completed",
    "Activate Absolomon's account",
    "GDA6 automation is done",
    "Check reconciliation for Ibras95",
    "All DP World tasks are done",
    "Add call Amer about the EIR OCR model",
]
VOCAB = ["DP World", "EIR", "EIRs", "DPW", "GGEA", "Jebel Ali", "Absolomon", "GDA6", "Ibras95", "Amer", "EIR OCR"]


def synthesize(text: str, path: str):
    import win32com.client
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18   # SAFT16kHz16BitMono
    stream.Format = fmt
    stream.Open(path, 3)   # SSFMCreateForWrite
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Rate = 1
    voice.Speak(text)
    stream.Close()


def load(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    audio = pcm.astype(np.float32) / 32768.0
    return np.concatenate([np.zeros(4000, np.float32), audio, np.zeros(4000, np.float32)])


def words(s: str):
    return re.findall(r"[a-z0-9]+", s.lower())


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), int)
    d[:, 0] = range(len(r) + 1)
    d[0, :] = range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r), len(h)] / max(1, len(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--groq", action="store_true")
    ap.add_argument("--model", default="small")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    tmp = tempfile.mkdtemp(prefix="stt-bench-")
    clips = []
    for i, p in enumerate(PHRASES):
        path = os.path.join(tmp, f"{i}.wav")
        synthesize(p, path)
        clips.append((p, load(path)))

    from dit.transcriber import Transcriber
    local = Transcriber(args.model)
    setups = [
        ("local, no hints, beam 1", lambda a: local.transcribe(a, "en", 1)),
        ("local, vocab hints, beam 5", lambda a: local.transcribe(a, "en", 5, hotwords=" ".join(VOCAB))),
    ]
    if args.groq:
        from dit.env import load_dotenv, get_secret
        from dit.cloud_stt import GroqTranscriber, speech_span
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        groq = GroqTranscriber(get_secret("GROQ_API_KEY"))
        prompt = "Vocabulary: " + ", ".join(VOCAB) + "."

        def run_groq(a, with_prompt):
            s, e = speech_span(a) or (0, len(a))
            return groq.transcribe(a[s:e], 16000, "en", prompt if with_prompt else "")
        setups += [("groq large-v3, no hints", lambda a: run_groq(a, False)),
                   ("groq large-v3, vocab hints", lambda a: run_groq(a, True))]

    for name, fn in setups:
        total, ms = 0.0, []
        print(f"\n== {name}")
        for ref, audio in clips:
            t0 = time.perf_counter()
            hyp = fn(audio)
            ms.append((time.perf_counter() - t0) * 1000)
            e = wer(ref, hyp)
            total += e
            print(f"  {'ok ' if e == 0 else f'{e:.2f}'}  {hyp!r}")
        print(f"  -> mean WER {total / len(clips):.2f}, median {sorted(ms)[len(ms) // 2]:.0f}ms")


if __name__ == "__main__":
    main()

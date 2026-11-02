import time
import threading
from typing import Optional
from .config import Config
from .audio import AudioRecorder
from .transcriber import Transcriber
from .injector import TextInjector
from .feedback import FeedbackManager
from .overlay import StatusOverlay

class DictationEngine:
    def __init__(self, config: Config):
        self.config = config
        self.feedback = FeedbackManager(enabled=config.audio_cues)
        self.overlay = StatusOverlay(enabled=config.gui_overlay)
        self.recorder = AudioRecorder(samplerate=config.samplerate)
        self.transcriber = Transcriber(
            model_name=config.model_name,
            device=config.device,
            compute_type=config.compute_type
        )
        self.injector = TextInjector(
            mode=config.paste_mode,
            restore_clipboard=config.restore_clipboard,
            restore_delay_ms=config.restore_delay_ms
        )
        
        self.is_listening = False
        self._turn_count = 0
        self._epoch = 0
        self._start_time = 0.0
        self._lock = threading.Lock()

    def start_dictation(self):
        with self._lock:
            if self.is_listening:
                return
            self.is_listening = True
            self._epoch += 1
            self._start_time = time.time()
            self._turn_count += 1
            current_epoch = self._epoch

        print(f"\n[D^it Turn #{self._turn_count}] 🎙️ Listening... (Speak now)")
        self.feedback.start_recording()
        self.overlay.show_recording()
        
        try:
            self.recorder.start()
        except Exception as e:
            print(f"[D^it] Mic error: {e}")
            self.feedback.error()
            self.overlay.hide()
            with self._lock:
                self.is_listening = False

    def stop_dictation(self):
        with self._lock:
            if not self.is_listening:
                return
            self.is_listening = False
            current_epoch = self._epoch
            duration_audio = time.time() - self._start_time

        self.feedback.end_recording()
        self.overlay.show_transcribing()
        
        # Process transcription in background thread so hotkey hook doesn't lag
        threading.Thread(
            target=self._process_utterance,
            args=(current_epoch, duration_audio),
            daemon=True
        ).start()

    def _process_utterance(self, epoch: int, expected_duration: float):
        t_capture_start = time.time()
        audio = self.recorder.stop()
        t_capture_end = time.time()

        # If cancelled by newer turn
        with self._lock:
            if epoch != self._epoch:
                print(f"[D^it Turn #{self._turn_count}] Cancelled by newer turn.")
                return

        audio_len_s = len(audio) / self.config.samplerate if len(audio) > 0 else 0.0
        rms = self.recorder.calculate_rms(audio)

        if audio_len_s < 0.25 or rms < self.config.energy_threshold:
            print(f"[D^it Turn #{self._turn_count}] Discarded: Silence (Len: {audio_len_s:.2f}s, RMS: {rms:.4f})")
            self.feedback.empty_or_silence()
            self.overlay.hide()
            return

        print(f"[D^it Turn #{self._turn_count}] ⚡ Transcribing {audio_len_s:.2f}s audio (RMS: {rms:.4f})...")
        t_stt_start = time.time()
        try:
            text = self.transcriber.transcribe(
                audio,
                language=self.config.language,
                beam_size=self.config.beam_size
            )
        except Exception as e:
            print(f"[D^it Turn #{self._turn_count}] Transcription error: {e}")
            self.feedback.error()
            self.overlay.hide()
            return
        t_stt_end = time.time()

        with self._lock:
            if epoch != self._epoch:
                print(f"[D^it Turn #{self._turn_count}] Stale turn superseded.")
                return

        if not text:
            print(f"[D^it Turn #{self._turn_count}] No recognizable speech.")
            self.feedback.empty_or_silence()
            self.overlay.hide()
            return

        # Injection
        t_inj_start = time.time()
        self.injector.inject(text)
        t_inj_end = time.time()

        self.feedback.transcribed()
        self.overlay.show_success(text)

        # Telemetry & Structured Logging (lessons: instrument-stages-before-optimizing)
        stt_dur = t_stt_end - t_stt_start
        inj_dur = t_inj_end - t_inj_start
        total_latency = (t_inj_end - t_capture_start)

        print(
            f"[D^it Turn #{self._turn_count}] ✓ Injected:\n"
            f"  \"{text}\"\n"
            f"  [Timing] Audio: {audio_len_s:.2f}s | STT: {stt_dur*1000:.0f}ms | Inject: {inj_dur*1000:.0f}ms | Total Processing: {total_latency*1000:.0f}ms"
        )

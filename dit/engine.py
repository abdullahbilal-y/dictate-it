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
        
        self.tray = None
        self.listener = None
        self.task_manager = None   # set when tasks are enabled; receives "task" route transcripts
        self.cloud_stt = None      # GroqTranscriber when a Groq key is configured
        self.is_listening = False
        self._route = "dictate"
        self._turn_count = 0
        self._epoch = 0
        self._start_time = 0.0
        self._target_hwnd = None
        self._lock = threading.Lock()

    def set_tray(self, tray):
        self.tray = tray

    def set_listener(self, listener):
        self.listener = listener

    def set_task_manager(self, manager):
        self.task_manager = manager

    def set_cloud_stt(self, cloud):
        """GroqTranscriber (or None). Used for the routes listed in config.stt_cloud_routes."""
        self.cloud_stt = cloud

    def _vocabulary(self, route: str) -> list:
        terms = list(self.config.custom_vocabulary or [])
        if route == "task" and self.task_manager:
            terms += self.task_manager.vocabulary()
        seen, out = set(), []
        for t in terms:
            key = t.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(t.strip())
        return out

    def _transcribe(self, audio, route: str):
        """(text, engine label). Groq Whisper large-v3 when enabled for this route, local Whisper otherwise or
        whenever the cloud call fails. Both get the vocabulary (task titles + custom words) as spelling hints."""
        terms = self._vocabulary(route)
        cloud = getattr(self, "cloud_stt", None)
        if cloud and cloud.available and route in (self.config.stt_cloud_routes or []):
            from .cloud_stt import speech_span
            span = speech_span(audio, self.config.samplerate)
            if span is None:
                return "", "vad: no speech"
            prompt = ("Vocabulary: " + ", ".join(terms) + ".") if terms else ""
            try:
                text = cloud.transcribe(audio[span[0]:span[1]], self.config.samplerate,
                                        self.config.language, prompt)
                return text, f"groq {cloud.model}"
            except Exception as e:
                print(f"[STT] Groq failed ({e}); falling back to local Whisper.")
        beam = self.config.task_beam_size if route == "task" else self.config.beam_size
        text = self.transcriber.transcribe(audio, language=self.config.language, beam_size=beam,
                                           hotwords=" ".join(terms[:40]) if terms else None)
        return text, f"local {self.transcriber.model_name} beam {beam}"

    def start_dictation(self, route: str = "dictate"):
        """route: "dictate" pastes into the focused app; "task" hands the transcript to the task manager."""
        if route == "task" and not self.task_manager:
            route = "dictate"
        with self._lock:
            if self.is_listening:
                return
            self.is_listening = True
            self._route = route
            self._epoch += 1
            self._start_time = time.time()
            self._turn_count += 1
            # Capture the currently focused application window right when user presses hotkey
            self._target_hwnd = self.injector.get_foreground_window()
            current_epoch = self._epoch

        print(f"\n[D^it Turn #{self._turn_count}] 🎙️ Listening ({route})... (target window hwnd: {self._target_hwnd})")
        self.feedback.start_recording()
        if route == "task":
            self.task_manager.capture_started(level_fn=self.recorder.current_level)
        else:
            self.overlay.show_recording()
        if self.tray:
            self.tray.set_recording()
        
        threading.Thread(target=self._watchdog, args=(current_epoch, route), daemon=True).start()
        try:
            self.recorder.start()
        except Exception as e:
            print(f"[D^it] Mic error: {e}")
            self.feedback.error()
            self.overlay.hide()
            if route == "task":
                self.task_manager.capture_failed("error")
            if self.tray:
                self.tray.set_idle()
            with self._lock:
                self.is_listening = False

    def cancel_dictation(self) -> bool:
        """Esc while listening: throw the recording away. Nothing is transcribed, pasted or queued."""
        with self._lock:
            if not self.is_listening:
                return False
            self.is_listening = False
            self._epoch += 1
            route = self._route
        try:
            self.recorder.stop()
        except Exception as e:
            print(f"[D^it] Error stopping the mic on cancel: {e}")
        print(f"[D^it Turn #{self._turn_count}] Cancelled (Esc) - recording discarded.")
        self.feedback.empty_or_silence()
        self.overlay.hide()
        if route == "task" and self.task_manager:
            self.task_manager.capture_cancelled()
        if self.tray:
            self.tray.set_idle()
        return True

    def _watchdog(self, epoch: int, route: str):
        """Stops a recording that was forgotten (tap to start, never tapped to stop)."""
        limit = self.config.max_task_record_s if route == "task" else self.config.max_dictate_record_s
        time.sleep(max(5, limit))
        with self._lock:
            still = self.is_listening and self._epoch == epoch
        if still:
            print(f"[D^it Turn #{self._turn_count}] Auto-stopped after {limit}s (forgotten recording?)")
            self.stop_dictation()

    def stop_dictation(self):
        with self._lock:
            if not self.is_listening:
                return
            self.is_listening = False
            current_epoch = self._epoch
            target_hwnd = self._target_hwnd
            duration_audio = time.time() - self._start_time
            route = self._route

        self.feedback.end_recording()
        if route == "task":
            self.task_manager.capture_processing()
        else:
            self.overlay.show_transcribing()
        if self.tray:
            self.tray.set_transcribing()
        
        # Process transcription asynchronously so hotkey hook never hangs
        threading.Thread(
            target=self._process_utterance,
            args=(current_epoch, target_hwnd, duration_audio, route),
            daemon=True
        ).start()

    def _fail_turn(self, route: str, reason: str):
        self.overlay.hide()
        if route == "task":
            self.task_manager.capture_failed(reason)
        if self.tray:
            self.tray.set_idle()

    def _process_utterance(self, epoch: int, target_hwnd, expected_duration: float, route: str = "dictate"):
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

        if audio_len_s < 0.2 or rms == 0.0:
            print(f"[D^it Turn #{self._turn_count}] Discarded: Empty/too short (Len: {audio_len_s:.2f}s, RMS: {rms:.6f})")
            self.feedback.empty_or_silence()
            self._fail_turn(route, "silence")
            return

        print(f"[D^it Turn #{self._turn_count}] ⚡ Transcribing {audio_len_s:.2f}s audio (RMS: {rms:.6f})...")
        t_stt_start = time.time()
        try:
            text, stt_engine = self._transcribe(audio, route)
        except Exception as e:
            print(f"[D^it Turn #{self._turn_count}] Transcription error: {e}")
            self.feedback.error()
            self._fail_turn(route, "error")
            return
        t_stt_end = time.time()

        with self._lock:
            if epoch != self._epoch:
                print(f"[D^it Turn #{self._turn_count}] Stale turn superseded.")
                return

        if not text:
            print(f"[D^it Turn #{self._turn_count}] No recognizable speech (silence or filtered; {stt_engine}).")
            self.feedback.empty_or_silence()
            self._fail_turn(route, "silence")
            return

        if route == "task":
            t_task_start = time.time()
            result = self.task_manager.handle_command(text)
            t_task_end = time.time()
            if self.tray:
                self.tray.set_idle()
            print(
                f"[D^it Turn #{self._turn_count}] ✓ Task command ({result['action']} via {result['source']}):\n"
                f"  \"{text}\"\n"
                f"  [Timing] Audio: {audio_len_s:.2f}s | STT: {(t_stt_end - t_stt_start)*1000:.0f}ms ({stt_engine}) | "
                f"Intent: {result['intent_ms']:.0f}ms | Total Processing: {(t_task_end - t_capture_start)*1000:.0f}ms"
            )
            return

        # Text Injection directly into target window
        t_inj_start = time.time()
        self.injector.inject(text, target_hwnd=target_hwnd)
        t_inj_end = time.time()

        self.feedback.transcribed()
        self.overlay.show_success(text)
        if self.tray:
            self.tray.set_idle()

        # Telemetry & Structured Logging (lessons: instrument-stages-before-optimizing)
        stt_dur = t_stt_end - t_stt_start
        inj_dur = t_inj_end - t_inj_start
        total_latency = (t_inj_end - t_capture_start)

        print(
            f"[D^it Turn #{self._turn_count}] ✓ Injected:\n"
            f"  \"{text}\"\n"
            f"  [Timing] Audio: {audio_len_s:.2f}s | STT: {stt_dur*1000:.0f}ms ({stt_engine}) | Inject: {inj_dur*1000:.0f}ms | Total Processing: {total_latency*1000:.0f}ms"
        )

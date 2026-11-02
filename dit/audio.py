import threading
import numpy as np
import sounddevice as sd

class AudioRecorder:
    def __init__(self, samplerate: int = 16000):
        self.samplerate = samplerate
        self.frames = []
        self.is_recording = False
        self._stream = None
        self._lock = threading.Lock()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            # Drop/overflow warning
            pass
        if self.is_recording:
            # Flatten to 1D and copy
            self.frames.append(indata.flatten().copy())

    def start(self, device=None):
        with self._lock:
            if self.is_recording:
                return
            self.frames = []
            self.is_recording = True
            try:
                self._stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=1,
                    dtype="float32",
                    callback=self._audio_callback,
                    device=device,
                    blocksize=int(self.samplerate * 0.05)  # 50ms blocks
                )
                self._stream.start()
            except Exception as e:
                self.is_recording = False
                self._stream = None
                raise RuntimeError(f"Failed to start audio recording stream: {e}") from e

    def stop(self) -> np.ndarray:
        with self._lock:
            if not self.is_recording:
                return np.array([], dtype=np.float32)
            self.is_recording = False
            stream = self._stream
            self._stream = None

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not self.frames:
            return np.array([], dtype=np.float32)

        audio = np.concatenate(self.frames)
        self.frames = []
        return audio

    @staticmethod
    def calculate_rms(audio: np.ndarray) -> float:
        if audio is None or len(audio) == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio))))

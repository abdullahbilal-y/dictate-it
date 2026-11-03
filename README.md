# DictateIt 🎙️⚡

> **Blazing-fast, 100% private, local voice dictation for Windows powered by OpenAI Whisper and NVIDIA CUDA.**

Press **`Ctrl + Alt + D`** anywhere in Windows — speak naturally — and watch your words typed or pasted into whatever editor or application you have open (VS Code, Chrome, Notepad, Slack, Word, Discord, Terminal, etc.).

No cloud latency. No monthly subscriptions. No audio leaving your computer.

---

## 🌟 Why DictateIt is Unique

| Feature | DictateIt | Wispr Flow | Superwhisper | Windows (`Win+H`) |
| :--- | :---: | :---: | :---: | :---: |
| **Pricing** | **100% Free & Open Source** | $12–$15 / mo | $8.49/mo or $119 | Free |
| **Privacy** | **100% Local (Offline)** | Cloud (Sent to server) | Local / Cloud hybrid | Cloud |
| **Latency** | **~60ms–90ms** (CUDA float16) | ~600ms–1200ms | ~200ms–500ms | Variable |
| **Platform** | **Native Windows Optimized** | Win / Mac | Mac-first (Win Beta) | Windows |
| **Focus Locking** | ✅ Native HWND retention | ✅ App-based | ⚠️ Inconsistent on Win | ✅ Built-in |
| **Conflict-Free Key** | ✅ `Ctrl+Alt+D` | Custom | Custom | Fixed `Win+H` |

### Key Engineering Highlights:
- **Sub-100ms Inference:** Built on `faster-whisper` (CTranslate2) utilizing CUDA `float16` weights.
- **Hardened for Windows:**
  - **Focus-Locked Injection:** Automatically captures target application window (`GetForegroundWindow`) at the start of speech and guarantees focus restoration (`SetForegroundWindow`) right before pasting.
  - **Sticking Modifiers Flushed:** Releases virtual keys (`Shift`, `Ctrl`, `Alt`) via `keybd_event` before triggering paste, preventing corrupted `Ctrl+Shift+V` shortcuts.
  - **Neural VAD Pre-filtering:** Employs Silero VAD to filter background noise and silence without clipping soft voices.
- **Silent System Tray Resident:** Sits quietly in the notification area with real-time visual status dots (🔵 Idle, 🔴 Recording, 🟠 Transcribing).
- **Auto-Start Support:** Seamless one-click integration into Windows Startup (`shell:startup`) via headless VBScript (`pythonw.exe`).

---

## 📋 Requirements

- **Operating System:** Windows 10 or Windows 11 (64-bit).
- **Python:** Python 3.10 or 3.11 recommended.
- **GPU (Recommended for sub-100ms speed):**
  - NVIDIA GeForce GPU with CUDA support.
  - NVIDIA Driver installed.
  - *(Optional)* CPU execution (`int8`) is supported automatically as fallback.
- **Microphone:** Any standard headset or USB microphone.

---

## 🚀 Installation & Quick Start

### 1. Clone the Repository
```powershell
git clone https://github.com/abdullahbilal-y/dictate-it.git
cd dictate-it
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

*(If you need PyTorch with CUDA 12.4, install via: `pip install torch --index-url https://download.pytorch.org/whl/cu124`)*

### 3. Launch DictateIt

#### Option A: Silent in System Tray (No Terminal Window)
Double-click [**`start_tray.bat`**](start_tray.bat).  
DictateIt will start immediately in your Windows notification tray (near the clock) with zero command prompt window.

#### Option B: Terminal Console (With Live Telemetry)
Double-click [**`run_dit.bat`**](run_dit.bat) or run from PowerShell:
```powershell
python main.py
```

---

## 🎙️ How to Use

1. Focus any text field (VS Code, Google Chrome, Word, Slack, Notepad).
2. Press **`Ctrl + Alt + D`**.
   - You will hear a pleasant rising chirp.
   - The tray icon turns red (🔴).
3. Speak your thought.
4. Press **`Ctrl + Alt + D`** again (or release if using Push-to-Talk).
   - You will hear a confirmation chime.
   - The text is instantly typed/pasted right where your cursor is!

---

## ⚙️ Customization & Presets

Right-click the **DictateIt** icon in your system tray:

- **Shortcut Key Presets:**
  - `Ctrl + Alt + D` *(Default — Conflict-free)*
  - `Ctrl + Alt + Space` *(Thumb-friendly)*
  - `F8` *(One-touch dedicated key)*
  - `Alt + \` *(Symbol key)*
  - `Ctrl + Shift + D` *(Legacy)*
- **Mode Toggle:**
  - **Toggle Mode:** Press once to start, press again to stop.
  - **Push-to-Talk:** Hold shortcut while speaking, release to paste.
- **Start with Windows:** Toggle on/off to automatically run at Windows boot.
- **Sound Cues:** Enable or disable auditory chimes.

All changes are automatically saved to `config.json`.

---

## 🤖 Models & Offline Download

DictateIt uses `faster-whisper`. On first launch, the chosen model is automatically downloaded from HuggingFace to your local cache (`~/.cache/huggingface/hub/`):

| Model | GPU VRAM | Latency (RTX GPU) | Accuracy |
| :--- | :---: | :---: | :---: |
| **`tiny`** | ~500 MB | **~60ms–80ms** | Good for quick dictation |
| **`small`** *(Default)* | ~1.5 GB | **~80ms–150ms** | Great accuracy & speed balance |
| **`medium`** | ~3.5 GB | **~300ms–500ms** | High precision / multilingual |

To launch with a different model:
```powershell
python main.py --model tiny
```

---

## 🔄 Windows Startup Configuration

- **Via Tray:** Right-click tray icon -> check **Start with Windows**.
- **Via Script:** Double-click `add_to_startup.bat` (or `remove_from_startup.bat`).
- **Via CLI:**
  ```powershell
  python main.py --enable-startup
  python main.py --disable-startup
  ```

---

## 🛠️ Architecture & Landmines

DictateIt was engineered following production voice bot architecture:
- [brain/architecture.md](brain/architecture.md): Component diagrams & audio flow.
- [brain/landmines.md](brain/landmines.md): Known failure modes in Windows text injection, clipboard race conditions, and focus handling.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

Developed by [Abdullah Bilal](https://github.com/abdullahbilal-y).

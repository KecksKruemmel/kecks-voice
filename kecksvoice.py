import collections
import ctypes
import json
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request

import keyboard
import numpy as np
import pyperclip
import sounddevice as sd
from faster_whisper import WhisperModel
from PIL import Image, ImageChops, ImageDraw, ImageTk

try:
    import pystray
    HAVE_TRAY = True
except ImportError:
    HAVE_TRAY = False

try:
    import winreg
except ImportError:
    winreg = None

APP_NAME = "KecksVoice"
VERSION = "2.0"
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "kecksvoice.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SAMPLE_RATE = 16000
MIN_SECONDS = 0.4

DEFAULTS = {
    "hotkey": "right ctrl",
    "model": "small",
    "language": "auto",
    "ollama": False,
    "ollama_model": "llama3.2",
    "autostart": False,
    "theme": "dark",
}
MODELS = [("tiny", "Tiny"), ("base", "Base"), ("small", "Small"), ("medium", "Medium"), ("large-v3", "Large")]
THEMES = [("dark", "Dunkel"), ("glass", "Glas"), ("amethyst", "Amethyst")]
GLASS_THEMES = {"glass", "amethyst"}
LANGS = [("auto", "Auto"), ("de", "Deutsch"), ("en", "Englisch")]
KEY_NAMES = {
    "right shift": "Shift rechts",
    "right ctrl": "Strg rechts",
    "right alt": "Alt Gr",
    "alt gr": "Alt Gr",
    "caps lock": "Feststelltaste",
    "scroll lock": "Rollen",
    "pause": "Pause",
}
BLOCKED_KEYS = {"space", "enter", "backspace", "tab", "delete", "esc", "shift", "ctrl", "alt",
                "left windows", "right windows", "windows"}

DARK_BG = "#171310"
GLASS_BG = "#000000"
BG = DARK_BG
SURFACE = "#211b17"
RAISED = "#2c241f"
HOVER = "#342b25"
LINE = "#2b231e"
EDGE = "#40352d"
LIP = "#0e0b09"
TEXT = "#efe6dc"
MUTED = "#9a8b7e"
ACCENT = "#d39256"
ON_ACCENT = "#1b140f"
GOOD = "#6fbf8a"
BAD = "#e2614f"
OV_BG = "#1d1814"
OV_LINE = "#3a3029"
OV_TEXT = TEXT
OV_MUTED = MUTED
OV_ACCENT = ACCENT
OV_GOOD = GOOD
KEY = "#010101"

PALETTE_NAMES = ("SURFACE", "RAISED", "HOVER", "LINE", "EDGE", "LIP", "TEXT", "MUTED",
                 "ACCENT", "ON_ACCENT", "GOOD", "BAD", "OV_BG", "OV_LINE")
KEKS_PALETTE = {name: globals()[name] for name in PALETTE_NAMES}
AMETHYST_PALETTE = {
    "SURFACE": "#161a33", "RAISED": "#1f2446", "HOVER": "#282e58", "LINE": "#1e2342",
    "EDGE": "#363c6e", "LIP": "#0a0c1a", "TEXT": "#e4d8ff", "MUTED": "#8c82b4",
    "ACCENT": "#7f8cff", "ON_ACCENT": "#0b0f24", "GOOD": "#8cc8ff", "BAD": "#ff6b8b",
    "OV_BG": "#121530", "OV_LINE": "#2e3466",
}

FONT, SEMI = "Segoe UI", "Segoe UI Semibold"
SS = 4
RADIUS = 6
WIN_W, PAD = 420, 24
IW = WIN_W - 2 * PAD
METER_SEGMENTS = 24

FILLERS = {
    "de": r"\b(?:äh+m?|ähm+|öh+m?|öhm+|hm+|mhm+)\b",
    "en": r"\b(?:u+h+m*|u+m+|e+r+m*|hmm+|mhm+)\b",
}

try:
    import winsound

    def beep(freq, ms=60):
        threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()
except ImportError:
    def beep(freq, ms=60):
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def autostart_command():
    if FROZEN:
        return f'"{sys.executable}" --tray'
    py = sys.executable
    pyw = py[:-10] + "pythonw.exe" if py.lower().endswith("python.exe") else py
    return f'"{pyw}" "{os.path.abspath(__file__)}" --tray'


def set_autostart(enabled):
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def key_label(name):
    return KEY_NAMES.get(name, name.upper() if len(name) <= 3 else name.title())


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def rgba(h, a):
    return rgb(h) + (max(0, min(255, int(a))),)


def down(img, w, h):
    return img.resize((int(w), int(h)), Image.Resampling.BOX)


def fade(img, a):
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return out


def cookie_image(size=64, bite=True):
    S = size * SS
    u = S / 100
    img = Image.new("RGBA", (S, S), rgba("#e0a35a", 0))
    d = ImageDraw.Draw(img)
    d.ellipse([3 * u, 3 * u, 97 * u, 97 * u], fill="#b26c2c")
    d.ellipse([6 * u, 5 * u, 94 * u, 92 * u], fill="#e0a35a")
    d.ellipse([15 * u, 11 * u, 68 * u, 50 * u], fill="#eab66f")
    for x, y, r in [(31, 30, 7), (57, 25, 6), (24, 57, 6.5), (49, 50, 7.5), (72, 62, 6), (41, 76, 6), (76, 42, 5)]:
        d.ellipse([(x - r) * u, (y - r) * u, (x + r) * u, (y + r * 0.85) * u], fill="#4a2a16")
        d.ellipse([(x - r * 0.5) * u, (y - r * 0.55) * u, (x - r * 0.05) * u, (y - r * 0.15) * u], fill="#6e4426")
    if bite:
        mask = Image.new("L", (S, S), 255)
        md = ImageDraw.Draw(mask)
        for cx, cy, r in ((88, 13, 14), (98, 29, 12), (75, 3, 11)):
            md.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=0)
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return down(img, size, size)


def dot(size, color):
    S = size * SS
    img = Image.new("RGBA", (S, S), rgba(color, 0))
    ImageDraw.Draw(img).ellipse([0, 0, S - 1, S - 1], fill=rgba(color, 255))
    return down(img, size, size)


def check_mark(size, color):
    S = size * SS
    img = Image.new("RGBA", (S, S), rgba(color, 0))
    ImageDraw.Draw(img).line([(0.15 * S, 0.55 * S), (0.4 * S, 0.8 * S), (0.85 * S, 0.25 * S)],
                             fill=rgba(color, 255), width=int(S * 0.14), joint="curve")
    return down(img, size, size)


def blend(a, b, p):
    return tuple(int(x + (y - x) * p) for x, y in zip(rgb(a), rgb(b)))


def set_palette(theme):
    global BG, OV_TEXT, OV_MUTED, OV_ACCENT, OV_GOOD
    BG = GLASS_BG if theme in GLASS_THEMES else DARK_BG
    globals().update(AMETHYST_PALETTE if theme == "amethyst" else KEKS_PALETTE)
    OV_TEXT, OV_MUTED, OV_ACCENT, OV_GOOD = TEXT, MUTED, ACCENT, GOOD


class MARGINS(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


def style_window(root, glass):
    def colorref(h):
        r, g, b = rgb(h)
        return r | g << 8 | b << 16
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        dwm = ctypes.windll.dwmapi

        def put(attr, val):
            v = ctypes.c_uint(val)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
        put(20, 1)
        m = -1 if glass else 0
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(m, m, m, m)))
        backdrop = put(38, 3 if glass else 1)
        put(34, 0xFFFFFFFF if glass else colorref(LINE))
        put(35, 0xFFFFFFFF if glass else colorref(BG))
        put(36, colorref(TEXT))
        return backdrop
    except Exception:
        return False


def clean_rules(text, lang):
    text = re.sub(FILLERS.get(lang, FILLERS["en"]), "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",(\s*,)+", ",", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")
    if text:
        text = text[0].upper() + text[1:]
    return text


def clean_llm(text, model):
    prompt = (
        "Bereinige dieses diktierte Transkript. Entferne Fuellwoerter und "
        "Selbstkorrekturen (behalte nur die endgueltige Aussage), korrigiere "
        "Gross und Kleinschreibung und Satzzeichen. Aendere sonst nichts, "
        "uebersetze nichts, fuege nichts hinzu. Gib NUR den bereinigten Text aus.\n\n"
        f"Transkript: {text}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())["response"].strip() or text
    except Exception:
        return text


def paste(text):
    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.15)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


class Engine:
    def __init__(self, cfg, events):
        self.cfg = cfg
        self.events = events
        self.model = None
        self.frames = []
        self.recording = False
        self.level = 0.0
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.stream = None

    def load_model(self):
        self.model = None
        self.events.put(("loading", self.cfg["model"]))
        try:
            self.model = WhisperModel(self.cfg["model"], device="cpu", compute_type="int8")
            self.events.put(("ready", None))
        except Exception as e:
            self.events.put(("error", f"Das Modell konnte nicht geladen werden: {e}"))

    def start_audio(self):
        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._cb
            )
            self.stream.start()
            self.events.put(("mic", sd.query_devices(kind="input")["name"]))
        except Exception as e:
            self.events.put(("error", f"Kein Mikrofon verfügbar: {e}"))
        threading.Thread(target=self._worker, daemon=True).start()

    def _cb(self, indata, frames, t, status):
        rms = float(np.sqrt(np.mean(indata ** 2)))
        self.level = min(1.0, rms * 14)
        if self.recording:
            self.frames.append(indata.copy())

    def start(self):
        if self.model is None:
            return
        with self.lock:
            if self.recording:
                return
            self.frames = []
            self.recording = True
        beep(900)
        self.events.put(("state", "rec"))

    def stop(self):
        with self.lock:
            if not self.recording:
                return
            self.recording = False
            frames, self.frames = self.frames, []
        beep(600)
        if not frames:
            self.events.put(("state", "idle"))
            return
        audio = np.concatenate(frames, axis=0).flatten()
        if len(audio) / SAMPLE_RATE < MIN_SECONDS:
            self.events.put(("state", "idle"))
            return
        self.events.put(("state", "proc"))
        self.jobs.put(audio)

    def _worker(self):
        while True:
            audio = self.jobs.get()
            try:
                lang = None if self.cfg["language"] == "auto" else self.cfg["language"]
                segments, info = self.model.transcribe(audio, language=lang, vad_filter=True, beam_size=5)
                raw = " ".join(s.text.strip() for s in segments).strip()
                if not raw:
                    self.events.put(("state", "idle"))
                    continue
                text = clean_rules(raw, info.language)
                if self.cfg["ollama"]:
                    text = clean_llm(text, self.cfg["ollama_model"])
                if text:
                    paste(text)
                    self.events.put(("done", text))
                else:
                    self.events.put(("state", "idle"))
            except Exception as e:
                self.events.put(("error", f"Fehler bei der Erkennung: {e}"))


class Overlay:
    W, H = 300, 52
    BARS = 24

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.win.configure(bg=KEY)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{sh - self.H - 90}")
        self.c = tk.Canvas(self.win, width=self.W, height=self.H, bg=KEY, highlightthickness=0)
        self.c.pack()
        self.win.withdraw()
        self.visible = False
        self.bars = collections.deque([0.0] * self.BARS, maxlen=self.BARS)
        self.rec_dot = dot(10, BAD)
        self.check = check_mark(14, OV_GOOD)
        self.photo = None

    def show(self):
        if not self.visible:
            self.bars.extend([0.0] * self.BARS)
            self.win.deiconify()
            self.win.attributes("-topmost", True)
            self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def draw(self, state, level, t, text=""):
        W, H = self.W, self.H
        cy = H / 2
        img = Image.new("RGBA", (W * SS, H * SS), rgba(KEY, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W * SS - 1, H * SS - 1], radius=H * SS // 2, fill=rgb(OV_LINE))
        d.rounded_rectangle([SS, SS, (W - 1) * SS - 1, (H - 1) * SS - 1],
                            radius=(H - 2) * SS // 2, fill=rgb(OV_BG))
        if state == "rec":
            self.bars.append(level)
            x = 136
            for v in self.bars:
                h = 3 + min(1.0, v * 1.3) * 24
                d.rounded_rectangle([x * SS, (cy - h / 2) * SS, (x + 3) * SS, (cy + h / 2) * SS],
                                    radius=SS * 1.5, fill=rgb(OV_ACCENT))
                x += 6
        elif state == "proc":
            for i in range(3):
                a = 0.35 + 0.65 * max(0.0, math.sin(t * 6 - i * 0.8))
                x, r = 252 + i * 12, 3
                color = tuple(int(c * a + b * (1 - a)) for c, b in zip(rgb(OV_ACCENT), rgb(OV_BG)))
                d.ellipse([(x - r) * SS, (cy - r) * SS, (x + r) * SS, (cy + r) * SS], fill=color)
        frame = down(img, W, H)
        if state == "rec":
            frame.alpha_composite(fade(self.rec_dot, 0.55 + 0.45 * math.sin(t * 6)), (22, int(cy - 5)))
        elif state == "done":
            frame.alpha_composite(self.check, (20, int(cy - 7)))
        self.photo = ImageTk.PhotoImage(frame)

        c = self.c
        c.delete("all")
        c.create_image(0, 0, image=self.photo, anchor="nw")
        if state == "rec":
            c.create_text(42, cy, text="Aufnahme", fill=OV_TEXT, anchor="w", font=(SEMI, 10))
        elif state == "proc":
            c.create_text(24, cy, text="Wird verarbeitet", fill=OV_TEXT, anchor="w", font=(SEMI, 10))
        elif state == "done":
            preview = text if len(text) <= 32 else text[:31] + "…"
            c.create_text(42, cy, text=preview, fill=OV_TEXT, anchor="w", font=(FONT, 10))


class Segmented(tk.Canvas):
    H = 30

    def __init__(self, master, options, value, command, width):
        super().__init__(master, width=width, height=self.H, bg=BG, highlightthickness=0, cursor="hand2")
        self.options, self.value, self.command, self.w = options, value, command, width
        self.hover = None
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda e: self._set_hover(self._idx(e.x)))
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self._draw()

    def _idx(self, x):
        return max(0, min(len(self.options) - 1, int(x / (self.w / len(self.options)))))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self._draw()

    def _click(self, e):
        v = self.options[self._idx(e.x)][0]
        if v != self.value:
            self.value = v
            self._draw()
            self.command(v)

    def _draw(self):
        n, h = len(self.options), self.H
        sw = self.w / n
        sel = next((i for i, (v, _) in enumerate(self.options) if v == self.value), 0)
        img = Image.new("RGBA", (self.w * SS, h * SS), rgba(SURFACE, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, self.w * SS - 1, h * SS - 1], radius=RADIUS * SS, fill=rgba(SURFACE, 255))
        x0, x1 = (sel * sw + 2) * SS, ((sel + 1) * sw - 2) * SS
        d.rounded_rectangle([x0, 2 * SS, x1, (h - 2) * SS], radius=(RADIUS - 2) * SS,
                            fill=blend(SURFACE, ACCENT, 0.2) + (255,), outline=blend(SURFACE, ACCENT, 0.55) + (255,),
                            width=SS)
        self.photo = ImageTk.PhotoImage(down(img, self.w, h))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        for i, (_, label) in enumerate(self.options):
            fg = ACCENT if i == sel else (TEXT if i == self.hover else MUTED)
            self.create_text((i + 0.5) * sw, h / 2, text=label, fill=fg, font=(SEMI if i == sel else FONT, 9))


class Toggle(tk.Canvas):
    W, H = 38, 22

    def __init__(self, master, value, command):
        super().__init__(master, width=self.W, height=self.H, bg=BG, highlightthickness=0, cursor="hand2")
        self.value, self.command = value, command
        self.pos = 1.0 if value else 0.0
        self.bind("<Button-1>", self._click)
        self._draw()

    def set(self, value):
        self.value = value
        self._animate()

    def _click(self, _):
        self.value = not self.value
        self._animate()
        self.command(self.value)

    def _animate(self):
        target = 1.0 if self.value else 0.0
        self.pos += (target - self.pos) * 0.5
        if abs(target - self.pos) < 0.05:
            self.pos = target
        self._draw()
        if self.pos != target:
            self.after(16, self._animate)

    def _draw(self):
        W, H, p = self.W, self.H, self.pos
        track = tuple(int(a + (b - a) * p) for a, b in zip(rgb(EDGE), rgb(ACCENT)))
        img = Image.new("RGBA", (W * SS, H * SS), track + (0,))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W * SS - 1, H * SS - 1], radius=H * SS // 2, fill=track + (255,))
        k = H - 6
        x = 3 + p * (W - H)
        d.ellipse([x * SS, 3 * SS, (x + k) * SS, (3 + k) * SS], fill=rgba(TEXT, 255))
        self.photo = ImageTk.PhotoImage(down(img, W, H))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")


class KeyCap(tk.Canvas):
    H = 44

    def __init__(self, master, text, command):
        super().__init__(master, height=self.H + 3, bg=BG, highlightthickness=0, cursor="hand2")
        self.font = tkfont.Font(family=SEMI, size=12)
        self.hover = self.active = False
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.set(text)

    def _hover(self, v):
        self.hover = v
        self._draw()

    def set(self, text, active=False):
        self.text, self.active = text, active
        self._draw()

    def _draw(self):
        h = self.H
        w = 160
        self.configure(width=w)
        face = ACCENT if self.active else (HOVER if self.hover else RAISED)
        img = Image.new("RGBA", (w * SS, (h + 3) * SS), rgba(EDGE, 0))
        d = ImageDraw.Draw(img)
        r = RADIUS * SS
        d.rounded_rectangle([0, 3 * SS, w * SS - 1, (h + 3) * SS - 1], radius=r, fill=rgba(LIP, 255))
        d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r, fill=rgba(face, 255),
                            outline=rgba(EDGE, 255), width=SS)
        self.photo = ImageTk.PhotoImage(down(img, w, h + 3))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        self.create_text(w / 2, h / 2, text=self.text, fill=ON_ACCENT if self.active else TEXT, font=self.font)


class Meter(tk.Canvas):
    def __init__(self, master, segments=METER_SEGMENTS, seg_w=4, gap=2, height=14):
        width = segments * (seg_w + gap) - gap
        super().__init__(master, width=width, height=height, bg=BG, highlightthickness=0)
        self.items = [self.create_rectangle(i * (seg_w + gap), 0, i * (seg_w + gap) + seg_w, height,
                                            fill=EDGE, outline="") for i in range(segments)]
        self.shown = -1
        self.peak = 0.0

    def update_level(self, level, color):
        self.peak = max(level, self.peak * 0.85)
        n = round(min(1.0, self.peak * 1.4) * len(self.items))
        key = (n, color)
        if key == self.shown:
            return
        self.shown = key
        for i, item in enumerate(self.items):
            self.itemconfigure(item, fill=color if i < n else EDGE)


class LinkButton(tk.Label):
    def __init__(self, master, text, command):
        super().__init__(master, text=text, bg=BG, fg=MUTED, font=(FONT, 9), cursor="hand2")
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self.configure(fg=TEXT))
        self.bind("<Leave>", lambda e: self.configure(fg=MUTED))


STATUS = {
    "loading": ("MUTED", "Modell wird geladen"),
    "idle": ("GOOD", "Bereit"),
    "rec": ("BAD", "Aufnahme"),
    "proc": ("ACCENT", "Wird verarbeitet"),
    "done": ("GOOD", "Eingefügt"),
    "error": ("BAD", "Fehler"),
}


class App:
    def __init__(self):
        self.cfg = load_config()
        self.events = queue.Queue()
        self.engine = Engine(self.cfg, self.events)
        self.state = "loading"
        self.done_until = 0.0
        self.hook_handles = []
        self.capturing = False
        self.hist_rows = []
        self.dots = {}
        self.hint_reset = None
        self.last_text = ""
        self.state_msg = None
        self.history = []
        self.mic_name = "Mikrofon wird gesucht"
        self.body = None

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.icon_photo = ImageTk.PhotoImage(cookie_image(64))
        self.root.iconphoto(True, self.icon_photo)
        self.rebuild()
        self._fit_window()
        self.overlay = Overlay(self.root)

        threading.Thread(target=self._boot, daemon=True).start()
        self.bind_hotkey()
        self.tick()
        self.start_tray()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if "--tray" in sys.argv and getattr(self, "tray", None):
            self.root.withdraw()

    def _boot(self):
        self.engine.start_audio()
        self.engine.load_model()

    def _rule(self, parent, top=18, bottom=16):
        tk.Frame(parent, bg=LINE, height=1).pack(fill="x", pady=(top, bottom))

    def _heading(self, parent, text, note=None):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text=text, bg=BG, fg=TEXT, font=(SEMI, 10)).pack(side="left")
        if note:
            tk.Label(row, text=note, bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="right")
        return row

    def _row(self, parent, title, sub=None, pady=(0, 14)):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=pady)
        txt = tk.Frame(row, bg=BG)
        txt.pack(side="left")
        tk.Label(txt, text=title, bg=BG, fg=TEXT, font=(FONT, 10)).pack(anchor="w")
        if sub:
            tk.Label(txt, text=sub, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=IW - 70, justify="left").pack(anchor="w")
        return row

    def rebuild(self):
        theme = self.cfg.get("theme", "dark")
        set_palette(theme)
        if self.body is not None:
            self.body.destroy()
        self.root.configure(bg=BG)
        self.hist_rows = []
        self._build()
        for text, stamp in reversed(self.history):
            self.add_history(text, stamp)
        self.set_state(self.state, self.state_msg)
        self.root.update_idletasks()
        self.root.geometry(f"{WIN_W}x{self.root.winfo_reqheight()}")
        if not style_window(self.root, theme in GLASS_THEMES) and theme in GLASS_THEMES:
            self.cfg["theme"] = "dark"
            save_config(self.cfg)
            self.rebuild()
            self.flash_hint("Der Glas-Effekt braucht Windows 11.")

    def _build(self):
        body = self.body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=PAD, pady=(16, 14))

        head = tk.Frame(body, bg=BG)
        head.pack(fill="x")
        self.logo_photo = ImageTk.PhotoImage(cookie_image(22))
        tk.Label(head, image=self.logo_photo, bg=BG).pack(side="left")
        tk.Label(head, text=APP_NAME, bg=BG, fg=TEXT, font=(SEMI, 12)).pack(side="left", padx=(8, 0))
        self.status = tk.Label(head, bg=BG, fg=TEXT, font=(FONT, 9))
        self.status.pack(side="right")
        self.status_dot = tk.Label(head, bg=BG)
        self.status_dot.pack(side="right", padx=(0, 6))
        self._rule(body, 14, 18)

        tk.Label(body, text="Zum Diktieren gedrückt halten", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        key_row = tk.Frame(body, bg=BG)
        key_row.pack(fill="x", pady=(6, 0))
        self.keycap = KeyCap(key_row, key_label(self.cfg["hotkey"]), self.capture_hotkey)
        self.keycap.pack(side="left")
        mic = tk.Frame(key_row, bg=BG)
        mic.pack(side="right", pady=(4, 0))
        self.meter = Meter(mic)
        self.meter.pack(anchor="e")
        self.mic_label = tk.Label(mic, text=self.mic_name, bg=BG, fg=MUTED, font=(FONT, 8),
                                  anchor="e")
        self.mic_label.pack(anchor="e", pady=(5, 0))
        hint_box = tk.Frame(body, bg=BG, height=44)
        hint_box.pack(fill="x", pady=(8, 0))
        hint_box.pack_propagate(False)
        self.hint = tk.Label(hint_box, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=IW, justify="left",
                             anchor="nw")
        self.hint.pack(fill="both", expand=True)
        self._rule(body, 10, 16)

        self._heading(body, "Letzte Diktate", "Klicken zum Kopieren")
        self.hist_canvas = tk.Canvas(body, width=IW, height=164, bg=BG, highlightthickness=0, yscrollincrement=20)
        self.hist_canvas.pack(fill="x")
        self.hist_frame = tk.Frame(self.hist_canvas, bg=BG)
        self.hist_canvas.create_window(0, 0, window=self.hist_frame, anchor="nw", width=IW)
        self.hist_frame.bind("<Configure>", lambda e: self.hist_canvas.configure(
            scrollregion=(0, 0, IW, max(e.height, int(self.hist_canvas.cget("height"))))))
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.empty = tk.Label(self.hist_frame, bg=BG, fg=MUTED, font=(FONT, 9), justify="left", anchor="w", wraplength=IW,
                              text="Noch keine Diktate. Halte die Taste oben gedrückt und sprich.")
        self.empty.pack(fill="x", pady=(4, 0))
        self._rule(body, 10, 16)

        self._heading(body, "Einstellungen")
        self._row(body, "Darstellung", "Glas und Amethyst brauchen Windows 11.", pady=(0, 8))
        Segmented(body, THEMES, self.cfg.get("theme", "dark"), self.on_theme, IW).pack(pady=(0, 16))
        row = self._row(body, "Sprache")
        Segmented(row, LANGS, self.cfg["language"], self.on_lang, 252).pack(side="right")
        self._row(body, "Modell", "Größer ist genauer, aber langsamer.", pady=(0, 8))
        Segmented(body, MODELS, self.cfg["model"], self.on_model, IW).pack(pady=(0, 16))
        row = self._row(body, "Nachbearbeitung mit Ollama", "Entfernt Versprecher und Korrekturen.")
        Toggle(row, self.cfg["ollama"], self.on_llm).pack(side="right")
        row = self._row(body, "Mit Windows starten", "Startet minimiert im Infobereich.", pady=(0, 0))
        self.tg_auto = Toggle(row, self.cfg["autostart"], self.on_autostart)
        self.tg_auto.pack(side="right")
        self._rule(body, 18, 12)

        foot = tk.Frame(body, bg=BG)
        foot.pack(fill="x")
        tk.Label(foot, text=f"Version {VERSION}", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        LinkButton(foot, "Beenden", self.quit).pack(side="right")

    def _fit_window(self):
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{WIN_W}x{h}+{(sw - WIN_W) // 2}+{max(0, (sh - h) // 2 - 30)}")

    def _wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is not None and str(w).startswith(str(self.hist_canvas)):
            if self.hist_frame.winfo_height() > self.hist_canvas.winfo_height():
                self.hist_canvas.yview_scroll(-e.delta // 120, "units")

    def add_history(self, text, stamp=None):
        if stamp is None:
            stamp = time.strftime("%H:%M")
            self.history.insert(0, (text, stamp))
            del self.history[50:]
        self.empty.pack_forget()
        wrap = tk.Frame(self.hist_frame, bg=BG, cursor="hand2")
        if self.hist_rows:
            wrap.pack(fill="x", before=self.hist_rows[0])
        else:
            wrap.pack(fill="x")
        self.hist_rows.insert(0, wrap)
        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x")
        when = tk.Label(row, text=stamp, bg=BG, fg=MUTED, font=(FONT, 9), width=7, anchor="nw")
        when.pack(side="left", anchor="n", pady=7, padx=(6, 0))
        shown = text if len(text) <= 180 else text[:179] + "…"
        body = tk.Label(row, text=shown, bg=BG, fg=TEXT, font=(FONT, 10), wraplength=IW - 80,
                        justify="left", anchor="w")
        body.pack(side="left", fill="x", expand=True, pady=7, padx=(0, 6))
        tk.Frame(wrap, bg=LINE, height=1).pack(fill="x")
        parts = (row, when, body)

        def hover(on):
            for p in parts:
                p.configure(bg=SURFACE if on else BG)

        def copy(_):
            pyperclip.copy(text)
            when.configure(text="Kopiert", fg=GOOD)
            self.root.after(1200, lambda: when.winfo_exists() and when.configure(text=stamp, fg=MUTED))

        for p in parts:
            p.bind("<Enter>", lambda e: hover(True))
            p.bind("<Leave>", lambda e: hover(False))
            p.bind("<Button-1>", copy)
        while len(self.hist_rows) > 50:
            self.hist_rows.pop().destroy()
        self.hist_canvas.yview_moveto(0)

    def on_theme(self, value):
        self.cfg["theme"] = value
        save_config(self.cfg)
        self.rebuild()

    def on_lang(self, value):
        self.cfg["language"] = value
        save_config(self.cfg)

    def on_model(self, value):
        self.cfg["model"] = value
        save_config(self.cfg)
        self.set_state("loading")
        threading.Thread(target=self.engine.load_model, daemon=True).start()

    def on_llm(self, value):
        self.cfg["ollama"] = value
        save_config(self.cfg)

    def on_autostart(self, want):
        if set_autostart(want):
            self.cfg["autostart"] = want
            save_config(self.cfg)
        else:
            self.tg_auto.set(False)
            self.flash_hint("Autostart ist nur unter Windows möglich.")

    def capture_hotkey(self):
        if self.capturing:
            return
        self.capturing = True
        self.unbind_hotkey()
        self.keycap.set("Taste drücken", active=True)
        self.show_hint("Drück die neue Taste. Esc bricht ab.", TEXT)

        def wait():
            while True:
                e = keyboard.read_event()
                if e.event_type == keyboard.KEY_DOWN:
                    self.root.after(0, self._captured, (e.name or "").lower())
                    return
        threading.Thread(target=wait, daemon=True).start()

    def _captured(self, name):
        self.capturing = False
        rejected = name and name != "esc" and (len(name) == 1 or name in BLOCKED_KEYS)
        if name and name != "esc" and not rejected:
            self.cfg["hotkey"] = name
            save_config(self.cfg)
        self.keycap.set(key_label(self.cfg["hotkey"]))
        self.bind_hotkey()
        if rejected:
            self.flash_hint(f"{key_label(name)} wird beim Tippen gebraucht. Wähle eine Taste wie Strg rechts oder Pause.")
        else:
            self.show_hint()

    def unbind_hotkey(self):
        for h in self.hook_handles:
            try:
                keyboard.unhook(h)
            except Exception:
                pass
        self.hook_handles = []

    def bind_hotkey(self):
        self.unbind_hotkey()
        try:
            k = self.cfg["hotkey"]
            self.hook_handles.append(keyboard.on_press_key(k, lambda e: self.engine.start()))
            self.hook_handles.append(keyboard.on_release_key(k, lambda e: self.engine.stop()))
        except Exception as e:
            self.events.put(("error", f"Die Taste konnte nicht registriert werden: {e}"))

    def start_tray(self):
        if not HAVE_TRAY:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Öffnen", lambda i, it: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Beenden", lambda i, it: self.root.after(0, self.quit)),
        )
        self.tray = pystray.Icon(APP_NAME, cookie_image(64), APP_NAME, menu)
        self.tray.run_detached()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if HAVE_TRAY and getattr(self, "tray", None):
            self.root.withdraw()
        else:
            self.quit()

    def default_hint(self):
        if self.state == "loading":
            return f"Modell {self.cfg['model']} wird geladen. Beim ersten Start dauert das etwas länger."
        return "Klick auf die Taste, um eine andere zu wählen."

    def show_hint(self, msg=None, color=MUTED):
        if self.hint_reset:
            self.root.after_cancel(self.hint_reset)
            self.hint_reset = None
        self.hint.configure(text=msg or self.default_hint(), fg=color)

    def flash_hint(self, msg):
        self.show_hint(msg, BAD)
        self.hint_reset = self.root.after(5000, self.show_hint)

    def set_state(self, state, msg=None):
        self.state = state
        self.state_msg = msg
        name, title = STATUS[state]
        color = globals()[name]
        if color not in self.dots:
            self.dots[color] = ImageTk.PhotoImage(dot(8, color))
        self.status_dot.configure(image=self.dots[color])
        self.status.configure(text=title)
        if state == "done":
            self.done_until = time.time() + 1.2
        if state == "error":
            self.show_hint(msg or "Unbekannter Fehler.", BAD)
        elif state in ("loading", "idle") and not self.capturing and not self.hint_reset:
            self.show_hint()

    def tick(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "loading":
                    self.set_state("loading")
                elif kind == "ready":
                    self.set_state("idle")
                elif kind == "state":
                    self.set_state(data)
                elif kind == "mic":
                    self.mic_name = data if len(data) <= 30 else data[:29] + "…"
                    self.mic_label.configure(text=self.mic_name)
                elif kind == "done":
                    self.last_text = data
                    self.add_history(data)
                    self.set_state("done")
                elif kind == "error":
                    self.set_state("error", data)
        except queue.Empty:
            pass

        t = time.time()
        if self.state == "done" and t >= self.done_until:
            self.set_state("idle")
        if self.state in ("rec", "proc", "done"):
            self.overlay.show()
            self.overlay.draw(self.state, self.engine.level, t, self.last_text)
        else:
            self.overlay.hide()
        if self.root.winfo_viewable():
            self.meter.update_level(self.engine.level, BAD if self.state == "rec" else ACCENT)
        self.root.after(33, self.tick)

    def quit(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            if getattr(self, "tray", None):
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()
        os._exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()

"""
KecksVoice: lokales Diktier-Tool von Kecks.

Hotkey halten, sprechen, loslassen. Der bereinigte Text wird ins aktive
Fenster eingefügt. Alles läuft lokal (faster-whisper).
Optional glättet ein lokales Ollama-Modell Selbstkorrekturen.
"""

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
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

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
}
MODELS = [("tiny", "Tiny"), ("base", "Base"), ("small", "Small"), ("medium", "Medium"), ("large-v3", "Large")]
LANGS = [("auto", "Auto"), ("de", "Deutsch"), ("en", "English")]
KEY_NAMES = {
    "right shift": "Rechte Shift",
    "right ctrl": "Rechte Strg",
    "right alt": "Alt Gr",
    "alt gr": "Alt Gr",
    "caps lock": "Feststell",
    "scroll lock": "Rollen",
    "pause": "Pause",
}
# Tasten, die beim normalen Tippen ständig gedrückt werden
BLOCKED_KEYS = {"space", "enter", "backspace", "tab", "delete", "esc", "shift", "ctrl", "alt",
                "left windows", "right windows", "windows"}

# Keks-Palette
BG = "#1a120c"
CARD = "#241911"
CARD2 = "#2f2117"
LINE = "#3d2b1e"
TEXT = "#fbeedd"
MUTED = "#a88f78"
ACCENT = "#f2a54a"
ACCENT_HI = "#ffc072"
GOOD = "#7ed99a"
BAD = "#ff6b5b"
KEY = "#010101"  # Transparenzfarbe für das Overlay

FONT, SEMI, BLACK = "Segoe UI", "Segoe UI Semibold", "Segoe UI Black"
SS = 4  # Supersampling für glatte Kanten
WIN_W, PAD, PADI = 440, 20, 18
CW = WIN_W - 2 * PAD
IW = CW - 2 * PADI
HERO_H = 150

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


# ---------- Grafik ----------
def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def rgba(h, a):
    return rgb(h) + (max(0, min(255, int(a))),)


def mix(a, b, p):
    return tuple(int(x + (y - x) * p) for x, y in zip(rgb(a), rgb(b)))


def down(img, w, h):
    return img.resize((int(w), int(h)), Image.Resampling.BOX)


def fade(img, a):
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return out


def rounded(w, h, r, fill, outline=None):
    img = Image.new("RGBA", (w * SS, h * SS), rgba(fill, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, w * SS - 1, h * SS - 1], radius=r * SS, fill=rgba(fill, 255),
        outline=rgba(outline, 255) if outline else None, width=SS if outline else 0)
    return down(img, w, h)


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


def halo(size, color, r, blur, alpha):
    img = Image.new("RGBA", (size, size), rgba(color, 0))
    c = size / 2
    ImageDraw.Draw(img).ellipse([c - r, c - r, c + r, c + r], fill=rgba(color, alpha))
    return img.filter(ImageFilter.GaussianBlur(blur))


def check_badge(size, color=GOOD, ring=CARD):
    S = size * SS
    img = Image.new("RGBA", (S, S), rgba(color, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, S - 1, S - 1], fill=rgba(color, 255), outline=rgba(ring, 255), width=int(S * 0.08))
    d.line([(0.29 * S, 0.52 * S), (0.44 * S, 0.67 * S), (0.72 * S, 0.37 * S)],
           fill=rgba(BG, 255), width=int(S * 0.11), joint="curve")
    return down(img, size, size)


def dot(size, color):
    S = size * SS
    img = Image.new("RGBA", (S, S), rgba(color, 0))
    ImageDraw.Draw(img).ellipse([0, 0, S - 1, S - 1], fill=rgba(color, 255))
    return down(img, size, size)


def dark_titlebar(root):
    """Windows 11: Titelleiste in Schokobraun statt Weiß."""
    def colorref(h):
        r, g, b = rgb(h)
        return r | g << 8 | b << 16
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        for attr, val in ((20, 1), (34, colorref(LINE)), (35, colorref(BG)), (36, colorref(TEXT))):
            v = ctypes.c_int(val)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


# ---------- Text ----------
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
    """Aufnahme, Transkription, Einfügen. Meldet per Queue an die UI."""

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
            self.events.put(("error", f"Modell konnte nicht geladen werden: {e}"))

    def start_audio(self):
        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=self._cb
            )
            self.stream.start()
        except Exception as e:
            self.events.put(("error", f"Mikrofon-Fehler: {e}"))
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
                self.events.put(("error", f"Fehler: {e}"))


# ---------- Widgets ----------
class Overlay:
    """Schwebende Keks-Pille am unteren Bildschirmrand."""

    W, H = 330, 60
    BARS = 26

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
        self.cookie = cookie_image(36)
        self.check = check_badge(36)
        self.rec_dot = dot(12, BAD)
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
        d.rounded_rectangle([0, 0, W * SS - 1, H * SS - 1], radius=H * SS // 2, fill=rgb(LINE))
        d.rounded_rectangle([2 * SS, 2 * SS, (W - 2) * SS - 1, (H - 2) * SS - 1],
                            radius=(H - 4) * SS // 2, fill=rgb(CARD))
        if state == "rec":
            self.bars.append(level)
            x = 150
            for i, v in enumerate(self.bars):
                h = 4 + min(1.0, v * 1.3) * 30
                color = mix(LINE, ACCENT, 0.35 + 0.65 * i / (self.BARS - 1))
                d.rounded_rectangle([x * SS, (cy - h / 2) * SS, (x + 4) * SS, (cy + h / 2) * SS],
                                    radius=2 * SS, fill=color)
                x += 6.4
        elif state == "proc":
            for i in range(3):
                off = math.sin(t * 9 - i * 0.9) * 6
                x, y, r = 268 + i * 16, cy + off, 4.5
                d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=rgb(ACCENT))
        frame = down(img, W, H)

        icon = self.check if state == "done" else self.cookie
        if state == "proc":
            icon = icon.rotate(-t * 120, resample=Image.Resampling.BICUBIC)
        frame.alpha_composite(icon, (12, 12))
        if state == "rec":
            frame.alpha_composite(fade(self.rec_dot, 0.6 + 0.4 * math.sin(t * 7)), (38, 10))
        self.photo = ImageTk.PhotoImage(frame)

        c = self.c
        c.delete("all")
        c.create_image(0, 0, image=self.photo, anchor="nw")
        if state == "rec":
            c.create_text(60, cy, text="Ich höre zu", fill=TEXT, anchor="w", font=(SEMI, 11))
        elif state == "proc":
            c.create_text(60, cy, text="Schreibe …", fill=TEXT, anchor="w", font=(SEMI, 11))
        elif state == "done":
            preview = text if len(text) <= 34 else text[:33] + "…"
            c.create_text(60, cy - 9, text="Eingefügt", fill=GOOD, anchor="w", font=(SEMI, 10))
            c.create_text(60, cy + 10, text=preview, fill=MUTED, anchor="w", font=(FONT, 9))


class Segmented(tk.Canvas):
    """Pillenförmige Auswahl, z. B. Auto | Deutsch | English."""

    H = 34

    def __init__(self, master, options, value, command, width, bg=CARD, track=CARD2):
        super().__init__(master, width=width, height=self.H, bg=bg, highlightthickness=0, cursor="hand2")
        self.options, self.value, self.command, self.w, self.track = options, value, command, width, track
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
        img = Image.new("RGBA", (self.w * SS, h * SS), rgba(self.track, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, self.w * SS - 1, h * SS - 1], radius=h * SS // 2, fill=rgba(self.track, 255))

        def pill(i, color):
            d.rounded_rectangle([(i * sw + 3) * SS, 3 * SS, ((i + 1) * sw - 3) * SS, (h - 3) * SS],
                                radius=(h - 6) * SS // 2, fill=rgba(color, 255))
        if self.hover is not None and self.hover != sel:
            pill(self.hover, LINE)
        pill(sel, ACCENT)
        self.photo = ImageTk.PhotoImage(down(img, self.w, h))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        for i, (_, label) in enumerate(self.options):
            fg = BG if i == sel else (TEXT if i == self.hover else MUTED)
            self.create_text((i + 0.5) * sw, h / 2, text=label, fill=fg, font=(SEMI, 9))


class Toggle(tk.Canvas):
    W, H = 46, 26

    def __init__(self, master, value, command):
        super().__init__(master, width=self.W, height=self.H, bg=CARD, highlightthickness=0, cursor="hand2")
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
        self.pos += (target - self.pos) * 0.45
        if abs(target - self.pos) < 0.03:
            self.pos = target
        self._draw()
        if self.pos != target:
            self.after(16, self._animate)

    def _draw(self):
        W, H, p = self.W, self.H, self.pos
        img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W * SS - 1, H * SS - 1], radius=H * SS // 2, fill=mix(LINE, ACCENT, p))
        k = H - 6
        x = 3 + p * (W - H)
        d.ellipse([x * SS, 3 * SS, (x + k) * SS, (3 + k) * SS], fill=mix(MUTED, TEXT, p))
        self.photo = ImageTk.PhotoImage(down(img, W, H))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")


class KeyCap(tk.Canvas):
    """Tastenkappe, Klick startet die Tastenaufnahme."""

    H = 32

    def __init__(self, master, text, command, small=False):
        self.small = small
        self.h = 22 if small else self.H
        super().__init__(master, height=self.h + 3, bg=CARD, highlightthickness=0,
                         cursor="arrow" if small else "hand2")
        self.font = tkfont.Font(family=SEMI, size=8 if small else 10)
        self.hover = self.active = False
        if command:
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
        h = self.h
        w = self.font.measure(self.text) + (16 if self.small else 30)
        self.configure(width=w)
        img = Image.new("RGBA", (w * SS, (h + 3) * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        top = ACCENT if self.active else (LINE if self.hover else CARD2)
        r = (6 if self.small else 9) * SS
        d.rounded_rectangle([0, 3 * SS, w * SS - 1, (h + 3) * SS - 1], radius=r, fill=rgb("#120c08"))
        d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=r, fill=rgb(top), outline=rgb(LINE), width=SS)
        self.photo = ImageTk.PhotoImage(down(img, w, h + 3))
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        self.create_text(w / 2, h / 2, text=self.text, fill=BG if self.active else ACCENT_HI, font=self.font)


class PillButton(tk.Canvas):
    def __init__(self, master, text, command, width=110, height=34):
        super().__init__(master, width=width, height=height, bg=BG, highlightthickness=0, cursor="hand2")
        self.text, self.w, self.h = text, width, height
        self.imgs = {v: ImageTk.PhotoImage(rounded(width, height, height // 2, c, LINE))
                     for v, c in ((False, CARD2), (True, LINE))}
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))
        self._draw(False)

    def _draw(self, hover):
        self.delete("all")
        self.create_image(0, 0, image=self.imgs[hover], anchor="nw")
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=TEXT if hover else MUTED, font=(SEMI, 9))


# ---------- App ----------
LOOK = {
    "loading": (MUTED, "Keks wird gebacken …"),
    "idle": (TEXT, "Bereit"),
    "rec": (BAD, "Ich höre zu …"),
    "proc": (ACCENT, "Schreibe …"),
    "done": (GOOD, "Eingefügt!"),
    "error": (BAD, "Hoppla"),
}
TONES = {"rec": BAD, "proc": ACCENT, "done": GOOD, "error": BAD, "loading": MUTED, "idle": ACCENT}


class App:
    def __init__(self):
        self.cfg = load_config()
        self.events = queue.Queue()
        self.engine = Engine(self.cfg, self.events)
        self.state = "loading"
        self.done_until = 0.0
        self.hook_handles = []
        self.capturing = False
        self.last_text = ""
        self.hero_dirty = True
        self.halos = {}
        self.hist_rows = []
        self.cards = []

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.icon_photo = ImageTk.PhotoImage(cookie_image(64))
        self.root.iconphoto(True, self.icon_photo)
        self.cookie_big = cookie_image(184)
        self.badge = check_badge(28)
        self._build()
        self.set_state("loading")
        self._fit_window()
        dark_titlebar(self.root)
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

    # ---------- Aufbau ----------
    def _card(self, parent, title=None, note=None):
        cv = tk.Canvas(parent, width=CW, height=40, bg=BG, highlightthickness=0)
        cv.pack(pady=(0, 14))
        inner = tk.Frame(cv, bg=CARD)
        cv.create_window(PADI, PADI, window=inner, anchor="nw", width=IW)
        inner.bind("<Configure>", lambda e: self._refit(cv, inner))
        self.cards.append((cv, inner))
        if title:
            head = tk.Frame(inner, bg=CARD)
            head.pack(fill="x", pady=(0, 10))
            tk.Label(head, text=title.upper(), bg=CARD, fg=MUTED, font=(SEMI, 8)).pack(side="left")
            if note:
                tk.Label(head, text=note, bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="right")
        return cv, inner

    @staticmethod
    def _refit(cv, inner):
        h = inner.winfo_reqheight() + 2 * PADI
        if getattr(cv, "fit_h", None) == h:
            return
        cv.fit_h = h
        cv.configure(height=h)
        cv.bg_img = ImageTk.PhotoImage(rounded(CW, h, 20, CARD, LINE))
        cv.delete("bg")
        cv.create_image(0, 0, image=cv.bg_img, anchor="nw", tags="bg")

    def _row(self, parent, title, sub=None, sep=True):
        if sep:
            tk.Frame(parent, bg=LINE, height=1).pack(fill="x", pady=11)
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x")
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left")
        tk.Label(txt, text=title, bg=CARD, fg=TEXT, font=(FONT, 10)).pack(anchor="w")
        if sub:
            tk.Label(txt, text=sub, bg=CARD, fg=MUTED, font=(FONT, 8)).pack(anchor="w")
        return row

    def _build(self):
        r = self.root
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(20, 16))
        self.logo_photo = ImageTk.PhotoImage(cookie_image(50))
        tk.Label(head, image=self.logo_photo, bg=BG).pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=12)
        tk.Label(titles, text=APP_NAME, bg=BG, fg=TEXT, font=(BLACK, 19)).pack(anchor="w")
        tk.Label(titles, text="Sprich. Es tippt.", bg=BG, fg=ACCENT, font=(FONT, 10)).pack(anchor="w")
        tk.Label(head, text="100 % lokal", bg=BG, fg=MUTED, font=(FONT, 8)).pack(side="right", anchor="n", pady=6)

        foot = tk.Frame(r, bg=BG)
        foot.pack(side="bottom", fill="x", padx=PAD, pady=(0, 16))
        PillButton(foot, "Beenden", self.quit).pack(side="right")
        tk.Label(foot, text="Frisch gebacken von Kecks", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")

        body = tk.Frame(r, bg=BG)
        body.pack(padx=PAD)

        _, hero = self._card(body)
        self.hero = tk.Canvas(hero, width=IW, height=HERO_H, bg=CARD, highlightthickness=0)
        self.hero.pack()
        self.hero_item = self.hero.create_image(0, 0, anchor="nw")
        self.status = tk.Label(hero, text="", bg=CARD, fg=TEXT, font=(SEMI, 16))
        self.status.pack(pady=(4, 2))
        hint_box = tk.Frame(hero, bg=CARD, width=IW, height=44)
        hint_box.pack()
        hint_box.pack_propagate(False)
        self.hint = tk.Frame(hint_box, bg=CARD)
        self.hint.place(relx=0.5, rely=0.5, anchor="center")
        self.hint_pre = tk.Label(self.hint, bg=CARD, fg=MUTED, font=(FONT, 10), wraplength=IW, justify="center")
        self.hint_key = KeyCap(self.hint, "", None, small=True)
        self.hint_post = tk.Label(self.hint, text="gedrückt und sprich", bg=CARD, fg=MUTED, font=(FONT, 10))

        self.tabs = Segmented(body, [("hist", "Verlauf"), ("set", "Einstellungen")], "hist",
                              self.show_tab, CW, bg=BG, track=CARD)
        self.tabs.pack(pady=(0, 14))

        self.hist_card, hist = self._card(body, "Zuletzt diktiert", "Klick kopiert")
        self.hist_inner = hist
        self.hist_canvas = tk.Canvas(hist, width=IW, height=200, bg=CARD, highlightthickness=0, yscrollincrement=20)
        self.hist_canvas.pack()
        self.hist_frame = tk.Frame(self.hist_canvas, bg=CARD)
        self.hist_canvas.create_window(0, 0, window=self.hist_frame, anchor="nw", width=IW)
        self.hist_frame.bind("<Configure>", lambda e: self.hist_canvas.configure(
            scrollregion=(0, 0, IW, max(e.height, int(self.hist_canvas.cget("height"))))))
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.empty = tk.Label(self.hist_frame, bg=CARD, fg=MUTED, font=(FONT, 10), justify="center",
                              text="Noch keine Krümel hier.\nHalte deine Taste und leg los.")
        self.empty.pack(pady=60)

        self.set_card, sc = self._card(body)
        self.set_inner = sc
        row = self._row(sc, "Aufnahme-Taste", "Klicken, dann neue Taste drücken", sep=False)
        self.keycap = KeyCap(row, key_label(self.cfg["hotkey"]), self.capture_hotkey)
        self.keycap.pack(side="right")
        row = self._row(sc, "Sprache")
        Segmented(row, LANGS, self.cfg["language"], self.on_lang, 240).pack(side="right")
        self._row(sc, "Modell", "Größer = genauer, aber langsamer")
        Segmented(sc, MODELS, self.cfg["model"], self.on_model, IW).pack(pady=(10, 0))
        row = self._row(sc, "KI-Feinschliff", "Lokales Ollama glättet Selbstkorrekturen")
        Toggle(row, self.cfg["ollama"], self.on_llm).pack(side="right")
        row = self._row(sc, "Mit Windows starten", "Startet leise im Tray")
        self.tg_auto = Toggle(row, self.cfg["autostart"], self.on_autostart)
        self.tg_auto.pack(side="right")

    def _fit_window(self):
        self.set_card.pack_forget()
        self.root.update_idletasks()
        hist_head = self.hist_inner.winfo_children()[0].winfo_reqheight() + 10
        self.hist_canvas.configure(height=self.set_inner.winfo_reqheight() - hist_head)
        self.root.update_idletasks()
        for cv, inner in self.cards:
            self._refit(cv, inner)
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{WIN_W}x{h}+{(sw - WIN_W) // 2}+{max(0, (sh - h) // 2 - 30)}")

    def show_tab(self, tab):
        show, hide = (self.hist_card, self.set_card) if tab == "hist" else (self.set_card, self.hist_card)
        hide.pack_forget()
        show.pack(pady=(0, 14))

    def _wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is not None and str(w).startswith(str(self.hist_canvas)):
            if self.hist_frame.winfo_height() > self.hist_canvas.winfo_height():
                self.hist_canvas.yview_scroll(-e.delta // 120, "units")

    # ---------- Verlauf ----------
    def add_history(self, text):
        self.empty.pack_forget()
        wrap = tk.Frame(self.hist_frame, bg=CARD, cursor="hand2")
        if self.hist_rows:
            wrap.pack(fill="x", before=self.hist_rows[0])
        else:
            wrap.pack(fill="x")
        self.hist_rows.insert(0, wrap)
        row = tk.Frame(wrap, bg=CARD)
        row.pack(fill="x")
        when = tk.Label(row, text=time.strftime("%H:%M"), bg=CARD, fg=MUTED, font=(SEMI, 8), width=7, anchor="nw")
        when.pack(side="left", anchor="n", pady=9, padx=(4, 0))
        shown = text if len(text) <= 180 else text[:179] + "…"
        body = tk.Label(row, text=shown, bg=CARD, fg=TEXT, font=(FONT, 10), wraplength=IW - 80,
                        justify="left", anchor="w")
        body.pack(side="left", fill="x", expand=True, pady=9, padx=(0, 8))
        tk.Frame(wrap, bg=LINE, height=1).pack(fill="x")

        parts = (row, when, body)
        stamp = when.cget("text")

        def hover(on):
            for p in parts:
                p.configure(bg=CARD2 if on else CARD)

        def copy(_):
            pyperclip.copy(text)
            when.configure(text="Kopiert ✓", fg=GOOD)
            self.root.after(1200, lambda: when.winfo_exists() and when.configure(text=stamp, fg=MUTED))

        for p in parts:
            p.bind("<Enter>", lambda e: hover(True))
            p.bind("<Leave>", lambda e: hover(False))
            p.bind("<Button-1>", copy)
        while len(self.hist_rows) > 50:
            self.hist_rows.pop().destroy()
        self.hist_canvas.yview_moveto(0)

    # ---------- Handler ----------
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
            self.events.put(("error", "Autostart geht nur unter Windows"))

    def capture_hotkey(self):
        if self.capturing:
            return
        self.capturing = True
        self.unbind_hotkey()
        self.keycap.set("Taste drücken …", active=True)

        def wait():
            while True:
                e = keyboard.read_event()
                if e.event_type == keyboard.KEY_DOWN:
                    self.root.after(0, self._captured, (e.name or "").lower())
                    return
        threading.Thread(target=wait, daemon=True).start()

    def _captured(self, name):
        self.capturing = False
        if name and name != "esc":
            if len(name) == 1 or name in BLOCKED_KEYS:
                self.events.put(("error", f"„{key_label(name)}“ brauchst du zum Tippen. Nimm lieber eine Sondertaste."))
            else:
                self.cfg["hotkey"] = name
                save_config(self.cfg)
        self.keycap.set(key_label(self.cfg["hotkey"]))
        self.bind_hotkey()
        self.refresh_hint()

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
            self.events.put(("error", f"Hotkey-Fehler: {e}"))

    # ---------- Tray ----------
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
        self.hero_dirty = True

    def on_close(self):
        if HAVE_TRAY and getattr(self, "tray", None):
            self.root.withdraw()
        else:
            self.quit()

    # ---------- Zustand ----------
    def set_hint(self, msg=None, color=MUTED):
        for w in (self.hint_pre, self.hint_key, self.hint_post):
            w.pack_forget()
        if msg is None:
            self.hint_pre.configure(text="Halte", fg=MUTED)
            self.hint_key.set(key_label(self.cfg["hotkey"]))
            self.hint_pre.pack(side="left")
            self.hint_key.pack(side="left", padx=6)
            self.hint_post.pack(side="left")
        else:
            self.hint_pre.configure(text=msg, fg=color)
            self.hint_pre.pack()

    def refresh_hint(self):
        if self.state == "idle":
            self.set_hint()

    def set_state(self, state, msg=None):
        self.state = state
        self.hero_dirty = True
        color, title = LOOK[state]
        self.status.configure(text=title, fg=color)
        if state == "loading":
            self.set_hint(f"Sprachmodell „{self.cfg['model']}“ wird geladen")
        elif state == "rec":
            self.set_hint("Loslassen zum Einfügen")
        elif state == "proc":
            self.set_hint("Gleich fertig")
        elif state == "done":
            self.done_until = time.time() + 1.2
            self.set_hint(self.last_text if len(self.last_text) <= 60 else self.last_text[:59] + "…")
        elif state == "error":
            self.set_hint(msg or "Unbekannter Fehler", BAD)
        else:
            self.set_hint()

    def render_hero(self, t):
        st, lvl = self.state, self.engine.level
        H = HERO_H
        ox = (IW - H) // 2
        tone = TONES[st]
        frame = Image.new("RGBA", (IW, H), rgba(CARD, 0))
        if tone not in self.halos:
            self.halos[tone] = halo(H, tone, 44, 16, 120)
        strength = {"rec": 0.5 + 0.5 * lvl, "idle": 0.55, "loading": 0.3}.get(st, 0.85)
        frame.alpha_composite(fade(self.halos[tone], strength), (ox, 0))

        S = H * SS
        c = S / 2
        layer = Image.new("RGBA", (S, S), rgba(tone, 0))
        d = ImageDraw.Draw(layer)

        def ring(radius, color, alpha, width):
            R = radius * SS
            d.ellipse([c - R, c - R, c + R, c + R], outline=rgba(color, alpha), width=max(1, int(width * SS)))
        base = 54
        if st == "rec":
            for i in range(3):
                p = (t * 0.7 + i / 3) % 1
                ring(base + p * 18, BAD, 190 * (1 - p), 2)
            ring(base - 2 + lvl * 8, ACCENT, 255, 3)
        elif st in ("proc", "loading"):
            ring(base, LINE, 255, 3)
            a0 = (t * 300) % 360
            R = base * SS
            d.arc([c - R, c - R, c + R, c + R], a0, a0 + 100, fill=rgba(tone, 255), width=3 * SS)
        else:
            ring(base, tone if st in ("done", "error") else LINE, 255, 2.5)
        frame.alpha_composite(down(layer, H, H), (ox, 0))

        cs = int(86 * (1 + 0.07 * lvl if st == "rec" else 1.0))
        ck = self.cookie_big.resize((cs, cs), Image.Resampling.LANCZOS)
        if st in ("proc", "loading"):
            ck = ck.rotate(-t * 90, resample=Image.Resampling.BICUBIC)
        if st == "loading":
            ck = fade(ck, 0.55)
        frame.alpha_composite(ck, (ox + (H - cs) // 2, (H - cs) // 2))
        if st == "done":
            frame.alpha_composite(self.badge, (ox + H // 2 + 16, H // 2 + 16))

        self.hero_photo = ImageTk.PhotoImage(frame)
        self.hero.itemconfigure(self.hero_item, image=self.hero_photo)

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
        if self.root.winfo_viewable() and (self.hero_dirty or self.state in ("rec", "proc", "loading")):
            self.render_hero(t)
            self.hero_dirty = False
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

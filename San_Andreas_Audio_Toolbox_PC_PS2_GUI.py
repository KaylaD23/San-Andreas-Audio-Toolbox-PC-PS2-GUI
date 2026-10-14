#!/usr/bin/env python3
"""San Andreas Audio Toolbox PC/PS2 GUI - audio workflows for GTA San Andreas.

The UI is new. The included PS2_PAK_Core module contains the archive/lookup
reader and writer used by this frontend. Because PS2 game revisions vary, always
keep a backup and test rebuilt assets in PCSX2 before installing them elsewhere.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import traceback
import tempfile
import datetime
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import PS2_PAK_Core as core
import PS2_Audio_Encoder as audio_encoder

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _TkBase = TkinterDnD.Tk
    DND_AVAILABLE = True
except ImportError:
    # The rest of the GUI remains usable without tkinterdnd2. The Track Browser
    # then offers a file-picker fallback instead of native OS drag-and-drop.
    DND_FILES = "DND_Files"
    _TkBase = tk.Tk
    DND_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageTk = None
    PIL_AVAILABLE = False

APP_TITLE = "San Andreas Audio Toolbox PC/PS2 GUI v3.0"
STATIONS = {
    "AA.PAK": "Police Radio / audio cues",
    "ADVERTS.PAK": "Advertisements",
    "AMBIENCE.PAK": "Ambience",
    "BEATS.PAK": "Beats / user music data",
    "CH.PAK": "Playback FM",
    "CO.PAK": "K-Rose",
    "CR.PAK": "K-DST",
    "CUTSCENE.PAK": "Cutscene audio",
    "DS.PAK": "Bounce FM",
    "HC.PAK": "SF-UR",
    "MH.PAK": "Radio Los Santos",
    "MR.PAK": "Radio X",
    "NJ.PAK": "CSR 103.9",
    "RE.PAK": "K-Jah Radio West",
    "RG.PAK": "Master Sounds 98.3",
    "TK.PAK": "WCTR",
}


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.1f} {unit}" if unit != "B" else f"{int(value):,} B"
        value /= 1024
    return f"{n:,} B"


def reveal_path(path: Path) -> None:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if sys.platform == "win32":
        os.startfile(str(path if path.is_dir() else path.parent))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path if path.is_dir() else path.parent)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


class Studio(_TkBase):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x1080")
        self.minsize(1000, 720)
        if sys.platform == "win32":
            # The reference is a maximized working window; do the same on Windows.
            self.after(80, lambda: self.state("zoomed"))
        self.configure(bg="#151914")

        self._header_base_image = None
        self._header_photo = None
        self._header_tk_native = None
        self._header_ppm_cache = None
        self._header_ppm_size = None
        self._header_last_size = None
        self._banner_container = None
        self._app_icon_photo = None
        self._set_app_icon()

        self.pak_var = tk.StringVar()
        self.lookup_var = tk.StringVar()
        self.station_var = tk.StringVar(value="TK.PAK — WCTR")
        self.group_var = tk.StringVar(value="Auto-detect")
        self.offset_var = tk.StringVar(value="Auto-detect")
        self.size_var = tk.StringVar(value="Auto-detect")
        self.extract_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.ffmpeg_var = tk.StringVar(value=shutil.which("ffmpeg") or "")
        self.status_var = tk.StringVar(value="Ready — choose a PS2 radio PAK and its matching TRAKLKUP.DAT.")
        self.project_state = tk.StringVar(value="No archive loaded")
        self.last_result = None
        self.last_tracks = []
        self.detected_group = None
        self._busy = False
        self._audio_import_busy = False
        self._audio_cancel_event = None
        self.dnd_enabled = DND_AVAILABLE

        # PC SAAT workflow state (uses the original bundled SAAT stream utility).
        self.pc_stream_var = tk.StringVar()
        self.pc_export_dir_var = tk.StringVar()
        self.pc_import_ini_var = tk.StringVar()
        self.pc_target_stream_var = tk.StringVar()
        self.pc_lookup_var = tk.StringVar()
        self.pc_status_var = tk.StringVar(value="PC SAAT ready — choose a PC audio stream file or folder.")

        self._set_style()
        self._build_menu()
        self._build_ui()
        self._station_changed()

    def _set_style(self):
        """GTA: San Andreas-inspired olive, asphalt and warm parchment theme."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.colors = {
            "bg": "#151914",
            "panel": "#22281f",
            "panel2": "#303a2b",
            "panel3": "#394532",
            "fg": "#f3ead1",
            "muted": "#c3b899",
            "accent": "#b9c99e",
            "accent2": "#4f6a43",
            "accent_hover": "#668458",
            "border": "#b8a879",
            "gold": "#e0cb94",
            "good": "#9fca8d",
            "warn": "#e7b366",
            "bad": "#d98b77",
        }
        c = self.colors
        base_font = ("Segoe UI", 10)
        style.configure(".", background=c["bg"], foreground=c["fg"], font=base_font)
        style.configure("TFrame", background=c["bg"])
        style.configure("Panel.TFrame", background=c["panel"])
        style.configure("Surface.TFrame", background="#0d120f")
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"])
        style.configure("Panel.TLabel", background=c["panel"], foreground=c["fg"])
        style.configure("Surface.TLabel", background="#0d120f", foreground=c["fg"])
        style.configure("Header.TLabel", background=c["bg"], foreground=c["fg"], font=("Georgia", 23, "bold"))
        style.configure("Subheader.TLabel", background=c["bg"], foreground=c["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=c["panel"], foreground=c["gold"], font=("Segoe UI", 11, "bold"))

        style.configure("TButton", background=c["panel2"], foreground=c["fg"],
                        padding=(11, 7), borderwidth=1, bordercolor=c["border"],
                        lightcolor=c["panel3"], darkcolor="#11150f", relief="raised")
        style.map("TButton",
                  background=[("active", c["accent_hover"]), ("pressed", c["accent2"]), ("disabled", c["panel"])],
                  foreground=[("disabled", "#827e70")],
                  bordercolor=[("active", c["gold"])])
        style.configure("Accent.TButton", background=c["accent2"], foreground="#fff4d8",
                        font=("Segoe UI", 10, "bold"), padding=(13, 8), borderwidth=1,
                        bordercolor=c["gold"], lightcolor=c["accent_hover"], darkcolor="#172016", relief="raised")
        style.map("Accent.TButton", background=[("active", c["accent_hover"]), ("pressed", "#2f472b")], foreground=[("disabled", "#aaa58d")])
        style.configure("TEntry", fieldbackground="#0b100d", foreground=c["fg"], insertcolor="#fff7e0",
                        bordercolor=c["border"], lightcolor=c["border"], darkcolor="#0a0d0a", padding=6)
        style.map("TEntry", bordercolor=[("focus", c["gold"])])
        style.configure("TCombobox", fieldbackground="#0b100d", background=c["panel2"], foreground=c["fg"],
                        arrowcolor=c["fg"], bordercolor=c["border"], lightcolor=c["border"], darkcolor="#0a0d0a", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#0b100d"), ("focus", "#101710")],
                  foreground=[("readonly", c["fg"])], background=[("active", c["accent2"])])
        style.configure("TLabelframe", background=c["panel"], foreground=c["fg"], bordercolor=c["border"], relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=c["panel"], foreground=c["gold"], font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 2, 0, 0))
        style.configure("TNotebook.Tab", background=c["panel2"], foreground=c["muted"], padding=(14, 8), borderwidth=1)
        style.map("TNotebook.Tab", background=[("selected", c["accent2"]), ("active", c["panel3"])],
                  foreground=[("selected", "#fff4d8"), ("active", c["fg"])], bordercolor=[("selected", c["gold"])])
        style.configure("Treeview", background="#0b100d", fieldbackground="#0b100d", foreground=c["fg"],
                        bordercolor=c["border"], rowheight=28, relief="flat", font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=c["panel2"], foreground=c["gold"], padding=(8, 8),
                        font=("Segoe UI", 9, "bold"), bordercolor=c["border"], relief="raised")
        style.map("Treeview", background=[("selected", "#4b6340")], foreground=[("selected", "#fff4d8")])
        style.configure("Vertical.TScrollbar", background=c["panel2"], troughcolor="#0b100d", arrowcolor=c["fg"], bordercolor=c["border"])
        style.configure("Horizontal.TScrollbar", background=c["panel2"], troughcolor="#0b100d", arrowcolor=c["fg"], bordercolor=c["border"])
        style.configure("Horizontal.TProgressbar", troughcolor="#0b100d", background=c["accent2"], bordercolor=c["border"])

    def _build_menu(self):
        menu = tk.Menu(self, tearoff=False, bg=self.colors["panel"], fg=self.colors["fg"], activebackground=self.colors["accent2"], activeforeground="#ffffff")
        file_menu = tk.Menu(menu, tearoff=False, bg=self.colors["panel"], fg=self.colors["fg"], activebackground=self.colors["accent2"], activeforeground="#ffffff")
        file_menu.add_command(label="Open radio PAK…", command=self._browse_pak)
        file_menu.add_command(label="Open TRAKLKUP.DAT…", command=self._browse_lookup)
        file_menu.add_command(label="Auto-rename track files…", command=self.auto_rename_files)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False, bg=self.colors["panel"], fg=self.colors["fg"], activebackground=self.colors["accent2"], activeforeground="#ffffff")
        help_menu.add_command(label="Open README", command=self._open_readme)
        help_menu.add_command(label="About", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self):
        # The banner bleeds to the full client width. Main work panels stay inset, like the reference.
        outer = ttk.Frame(self, padding=(0, 8, 0, 7))
        outer.pack(fill="both", expand=True)

        # The supplied GTA SA artwork is used as a real, responsive full-width banner.
        banner_path = Path(__file__).resolve().parent / "assets" / "gtasa_header.png"
        self._banner_container = outer
        self.banner_label = tk.Label(outer, text="SAN ANDREAS AUDIO TOOLBOX  ·  PC + PS2",
                                     bg=self.colors["bg"], fg=self.colors["gold"],
                                     font=("Georgia", 18, "bold"), bd=0, padx=12, pady=12, anchor="w")
        if banner_path.is_file():
            try:
                if PIL_AVAILABLE:
                    self._header_base_image = Image.open(banner_path).convert("RGB")
                    self._header_photo = ImageTk.PhotoImage(self._header_base_image)
                else:
                    self._header_tk_native = tk.PhotoImage(file=str(banner_path))
                    self._header_photo = self._header_tk_native
                self.banner_label.configure(image=self._header_photo, text="", compound="center")
            except Exception:
                pass
        self.banner_label.pack(fill="x", pady=(0, 8))
        # Resize from the actual outer/client width, not the image label's requested
        # width. This avoids the banner staying at its source-image width on systems
        # without Pillow and on maximized/DPI-scaled Windows windows.
        outer.bind("<Configure>", self._resize_header_banner, add="+")
        self.after_idle(self._resize_header_banner)

        content = ttk.Frame(outer, padding=(10, 0, 10, 0))
        content.pack(fill="both", expand=True)

        source = ttk.LabelFrame(content, text="  1  ·  Project source  ", padding=(12, 8))
        source.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(source, style="Panel.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Radio station", style="Panel.TLabel", width=14).pack(side="left")
        station_values = [f"{fname} — {name}" for fname, name in STATIONS.items()]
        self.station_combo = ttk.Combobox(row, textvariable=self.station_var, values=station_values, state="readonly", width=34)
        self.station_combo.pack(side="left", padx=(0, 8))
        self.station_combo.bind("<<ComboboxSelected>>", self._on_station_selected)
        ttk.Label(row, textvariable=self.project_state, style="Panel.TLabel").pack(side="left", padx=8)

        self._path_row(source, "Radio PAK", self.pak_var, self._browse_pak, "Select the station .PAK extracted from AUDIO/STREAMS")
        self._path_row(source, "TRAKLKUP.DAT", self.lookup_var, self._browse_lookup, "Select the matching table from AUDIO/CONFIG")
        format_row = ttk.Frame(source, style="Panel.TFrame")
        format_row.pack(fill="x", pady=(6, 1))
        ttk.Label(format_row, text="Archive ID", style="Panel.TLabel").pack(side="left")
        ttk.Combobox(format_row, textvariable=self.group_var, values=["Auto-detect"] + [f"0x{i:02X}" for i in range(256)], state="readonly", width=13).pack(side="left", padx=(7, 16))
        ttk.Label(format_row, text="Offset units", style="Panel.TLabel").pack(side="left")
        ttk.Combobox(format_row, textvariable=self.offset_var, values=["Auto-detect", "Bytes", "2048-byte LBA sectors"], state="readonly", width=19).pack(side="left", padx=(7, 16))
        ttk.Label(format_row, text="Size units", style="Panel.TLabel").pack(side="left")
        ttk.Combobox(format_row, textvariable=self.size_var, values=["Auto-detect", "Bytes", "2048-byte LBA sectors"], state="readonly", width=19).pack(side="left", padx=7)

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Inspect archive", style="Accent.TButton", command=self.inspect).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Extract tracks", command=self.extract).pack(side="left", padx=(0, 7))
        self.main_rebuild_button = ttk.Button(actions, text="REBUILD ARCHIVE + VERIFY", style="Accent.TButton", command=self.rebuild)
        self.main_rebuild_button.pack(side="left", padx=(0, 7))
        ttk.Label(actions, text="Replacement and conversion tools: Track Browser", style="Muted.TLabel").pack(side="right")

        # Reserve the compact status strip first so the expandable notebook cannot push it off-screen.
        footer = ttk.Frame(content)
        footer.pack(side="bottom", fill="x", pady=(7, 0))
        tk.Frame(footer, bg=self.colors["border"], height=1).pack(fill="x", pady=(0, 5))
        ttk.Label(footer, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Label(footer, text="BACK UP FIRST  ·  TEST IN PCSX2", style="Muted.TLabel").pack(side="right")

        self.tabs = ttk.Notebook(content)
        self.tabs.pack(fill="both", expand=True)
        self.browser_tab = ttk.Frame(self.tabs, padding=(10, 9, 10, 8))
        self.log_tab = ttk.Frame(self.tabs, padding=10)
        self.pc_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.browser_tab, text="PS2 Track Browser")
        self.tabs.add(self.pc_tab, text="PC SAAT")
        self.tabs.add(self.log_tab, text="Activity Log")
        self._build_browser_tab()
        self._build_pc_tab()
        self._build_log_tab()

    def _set_app_icon(self):
        """Apply the supplied SA emblem without letting Tk replace the native Windows ICO."""
        assets = Path(__file__).resolve().parent / "assets"
        ico_path = assets / "sa_app_icon.ico"
        png_path = assets / "sa_app_icon.png"
        png_64_path = assets / "sa_app_icon_64.png"
        # Explicitly set the icon on THIS root window. The `default=` argument
        # only establishes an icon for subsequently created toplevels on some Tk
        # builds, which can leave the main title bar showing Tk's generic icon.
        # The ICO contains pre-rendered native sizes so Windows can select a sharp
        # rendition instead of scaling one PNG for every surface.
        if sys.platform == "win32" and ico_path.is_file():
            try:
                self.iconbitmap(str(ico_path))
                try:
                    self.iconbitmap(default=str(ico_path))
                except tk.TclError:
                    pass
                return
            except tk.TclError:
                pass
        # Other platforms use the requested 64x64 PNG asset. Keep a reference
        # to prevent Tk from garbage-collecting the image.
        fallback = png_64_path if png_64_path.is_file() else png_path
        if fallback.is_file():
            try:
                self._app_icon_photo = tk.PhotoImage(file=str(fallback))
                self.iconphoto(True, self._app_icon_photo)
            except tk.TclError:
                pass

    @staticmethod
    def _parse_ppm(data: bytes):
        """Read the P6 PPM format emitted by Tk PhotoImage.write()."""
        index = 0
        tokens = []
        length = len(data)
        while len(tokens) < 4 and index < length:
            while index < length:
                value = data[index]
                if value in b" \t\r\n":
                    index += 1
                elif value == 35:  # '#'
                    while index < length and data[index] not in (10, 13):
                        index += 1
                else:
                    break
            start = index
            while index < length and data[index] not in b" \t\r\n#":
                index += 1
            if index > start:
                tokens.append(data[start:index])
        if len(tokens) != 4 or tokens[0] != b"P6":
            raise ValueError("Tk did not export the banner as a binary PPM image")
        width, height, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
        # Skip the separator after maxval (CRLF if emitted as a two-byte newline).
        if index < length and data[index] == 13 and index + 1 < length and data[index + 1] == 10:
            index += 2
        elif index < length and data[index] in b" \t\r\n":
            index += 1
        if maxval != 255:
            raise ValueError("Unsupported PPM channel depth")
        expected = width * height * 3
        rgb = data[index:index + expected]
        if len(rgb) != expected:
            raise ValueError("Truncated PPM banner image")
        return (width, height), rgb

    def _get_header_rgb_fallback(self):
        """Cache the source banner as RGB bytes when Pillow is unavailable."""
        if self._header_ppm_cache is not None:
            return self._header_ppm_size, self._header_ppm_cache
        native = self._header_tk_native
        if native is None:
            return None, None
        import tempfile
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as temp:
                temp_path = temp.name
            native.write(temp_path, format="ppm")
            image_size, rgb = self._parse_ppm(Path(temp_path).read_bytes())
            self._header_ppm_size, self._header_ppm_cache = image_size, rgb
            return image_size, rgb
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _bilinear_rgb(source_size, source_rgb, out_width, out_height):
        """Pure-Python bilinear resize used as a Pillow-free fallback."""
        sw, sh = source_size
        if sw == out_width and sh == out_height:
            return source_rgb
        out = bytearray(out_width * out_height * 3)
        xscale = (sw - 1) / max(1, out_width - 1)
        yscale = (sh - 1) / max(1, out_height - 1)
        out_i = 0
        for y in range(out_height):
            sy = y * yscale
            y0 = int(sy); y1 = min(y0 + 1, sh - 1); fy = sy - y0
            row0 = y0 * sw * 3
            row1 = y1 * sw * 3
            for x in range(out_width):
                sx = x * xscale
                x0 = int(sx); x1 = min(x0 + 1, sw - 1); fx = sx - x0
                i00 = row0 + x0 * 3; i10 = row0 + x1 * 3
                i01 = row1 + x0 * 3; i11 = row1 + x1 * 3
                for channel in range(3):
                    top = source_rgb[i00 + channel] * (1.0 - fx) + source_rgb[i10 + channel] * fx
                    bottom = source_rgb[i01 + channel] * (1.0 - fx) + source_rgb[i11 + channel] * fx
                    out[out_i] = max(0, min(255, int(top * (1.0 - fy) + bottom * fy + 0.5)))
                    out_i += 1
        return bytes(out)

    def _resize_header_banner(self, event=None):
        if self._banner_container is None or not hasattr(self, "banner_label"):
            return
        try:
            # The outer frame spans the full client area, unlike the image's natural width.
            width = int(event.width) if event is not None else int(self._banner_container.winfo_width())
            if width < 320:
                return  # wait for the first real layout pass
            width = max(320, width)
            # Slightly taller than a strict aspect-preserving crop, matching the reference.
            height = max(100, int(width * 0.141))
            size_key = (width, height)
            if size_key == self._header_last_size:
                return
            self._header_last_size = size_key
            if PIL_AVAILABLE and self._header_base_image is not None:
                resized = self._header_base_image.resize((width, height), Image.Resampling.LANCZOS)
                self._header_photo = ImageTk.PhotoImage(resized)
            else:
                source_size, source_rgb = self._get_header_rgb_fallback()
                if not source_rgb:
                    return
                rgb = self._bilinear_rgb(source_size, source_rgb, width, height)
                import tempfile
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as temp:
                        temp_path = temp.name
                        temp.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
                        temp.write(rgb)
                    self._header_photo = tk.PhotoImage(file=temp_path, format="ppm")
                finally:
                    if temp_path:
                        try:
                            Path(temp_path).unlink(missing_ok=True)
                        except OSError:
                            pass
            self.banner_label.configure(image=self._header_photo, text="")
        except Exception:
            # Keep the native image rather than preventing the rest of the UI from opening.
            pass

    def _path_row(self, parent, label, variable, command, hint=""):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, style="Panel.TLabel", width=14).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 7))
        ttk.Button(row, text="Browse…", command=command).pack(side="left")
        if hint:
            # Keep UI compact but show context as a small helper on next line.
            ttk.Label(parent, text=hint, style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w", padx=(116, 0), pady=(0, 1))

    def _build_browser_tab(self):
        bar = ttk.Frame(self.browser_tab, style="Panel.TFrame", padding=(10, 7))
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Archive contents", style="CardTitle.TLabel", font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Label(bar, text="Select a row to replace it, or drop audio to encode and replace one or more tracks.",
                  style="Panel.TLabel").pack(side="left", padx=14)

        table_shell = ttk.Frame(self.browser_tab, style="Panel.TFrame", padding=4)
        table_shell.pack(fill="both", expand=True)
        table_shell.rowconfigure(0, weight=1)
        table_shell.columnconfigure(0, weight=1)
        cols = ("entry", "file", "offset", "size", "type", "rate")
        self.track_tree = ttk.Treeview(table_shell, columns=cols, show="headings", selectmode="browse", height=6)
        labels = {"entry": "Lookup record", "file": "Extracted file", "offset": "PAK offset", "size": "Size", "type": "Detected format", "rate": "Sample rate"}
        widths = {"entry": 150, "file": 270, "offset": 150, "size": 125, "type": 180, "rate": 120}
        for c in cols:
            self.track_tree.heading(c, text=labels[c])
            self.track_tree.column(c, width=widths[c], anchor="center" if c in ("entry", "offset", "size", "rate") else "w", stretch=True)
        ys = ttk.Scrollbar(table_shell, orient="vertical", command=self.track_tree.yview)
        xs = ttk.Scrollbar(table_shell, orient="horizontal", command=self.track_tree.xview)
        self.track_tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.track_tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")

        drop_frame = ttk.LabelFrame(self.browser_tab, text="  Drop audio to encode + replace  ", padding=(9, 7))
        drop_frame.pack(fill="x", pady=(7, 0))
        dnd_hint = (
            "Drag WAV / MP3 / OGG / FLAC / AT3 audio here. Select a starting track first; multiple files fill subsequent rows."
            if DND_AVAILABLE else
            "Drop WAV / MP3 / OGG / FLAC / AT3 audio here. Select a starting track first; click this area to browse for audio."
        )
        self.drop_label = tk.Label(
            drop_frame, text=dnd_hint, bg="#0a100d", fg="#d5dfbe",
            relief="groove", bd=2, highlightthickness=1, highlightbackground=self.colors["border"],
            padx=8, pady=9, cursor="hand2", wraplength=1200,
            font=("Segoe UI", 10), anchor="center",
        )
        self.drop_label.pack(fill="x")
        self.drop_label.bind("<Button-1>", lambda _e: self.pick_audio_for_tracks())
        if self.dnd_enabled:
            try:
                self.drop_label.drop_target_register(DND_FILES)
                self.drop_label.dnd_bind("<<Drop>>", self._on_audio_drop)
                self.track_tree.drop_target_register(DND_FILES)
                self.track_tree.dnd_bind("<<Drop>>", self._on_audio_drop)
            except Exception as exc:
                self.dnd_enabled = False
                self.drop_label.configure(text=f"Drag-and-drop could not initialise: {exc}. Click here to choose audio files.")

        toggle_row = ttk.Frame(self.browser_tab)
        toggle_row.pack(fill="x", pady=(4, 0))
        self.advanced_toggle = ttk.Button(toggle_row, text="▸  Advanced replacement tools", command=self._toggle_advanced_tools)
        self.advanced_toggle.pack(side="right")

        # Keep the conversion/status strip visible at all times, as in the reference screenshot.
        progress_row = ttk.Frame(self.browser_tab, style="Panel.TFrame", padding=(8, 6))
        progress_row.pack(fill="x", pady=(3, 0))
        self.audio_progress_text = tk.StringVar(value="Ready for audio replacement.")
        ttk.Label(progress_row, textvariable=self.audio_progress_text, style="Panel.TLabel").pack(side="left", fill="x", expand=True)
        self.audio_progress = ttk.Progressbar(progress_row, orient="horizontal", mode="determinate", maximum=100, length=260)
        self.audio_progress.pack(side="left", padx=(8, 8))
        self.cancel_audio_button = ttk.Button(progress_row, text="Cancel conversion", command=self.cancel_audio_import, state="disabled")
        self.cancel_audio_button.pack(side="left")

        # Keep the screenshot-inspired main workspace clean; less-frequently used controls remain available here.
        self.advanced_tools_frame = ttk.Frame(self.browser_tab, style="Panel.TFrame", padding=(8, 7))
        controls = ttk.Frame(self.advanced_tools_frame, style="Panel.TFrame")
        controls.pack(fill="x", pady=(0, 7))
        ttk.Button(controls, text="Convert audio into selected track(s)…", style="Accent.TButton", command=self.pick_audio_for_tracks).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Replace selected PS2 data…", command=self.replace_selected).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Import matching files…", command=self.import_folder).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Auto-rename files…", command=self.auto_rename_files).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Open extracted folder", command=self.open_extract_folder).pack(side="left")

        workspace = ttk.LabelFrame(self.advanced_tools_frame, text="  Replacement workspace  ", padding=(9, 6))
        workspace.pack(fill="x")
        self._compact_path_row(workspace, "Extracted tracks", self.extract_var, self._browse_extract, "Folder used by replace/import/rebuild")
        self._compact_path_row(workspace, "Output folder", self.output_var, self._browse_output, "Destination for the new PAK and matching lookup")
        self._compact_path_row(workspace, "FFmpeg executable", self.ffmpeg_var, self._browse_ffmpeg, "Optional if ffmpeg is already on PATH")
        workflow = ttk.Frame(workspace, style="Panel.TFrame")
        workflow.pack(fill="x", pady=(5, 0))
        ttk.Button(workflow, text="Rebuild PAK + lookup and verify", style="Accent.TButton", command=self.rebuild).pack(side="left", padx=(0, 7))
        ttk.Button(workflow, text="Open output folder", command=self.open_output_folder).pack(side="left", padx=(0, 10))
        ttk.Label(workflow, text="Use NEW-*.PAK + NEW-TRAKLKUP.DAT together; back up game files and test the rebuild in PCSX2.",
                  style="Panel.TLabel", wraplength=600, justify="left").pack(side="left", fill="x", expand=True)

    def _toggle_advanced_tools(self):
        if self.advanced_tools_frame.winfo_manager():
            self.advanced_tools_frame.pack_forget()
            self.advanced_toggle.configure(text="▸  Advanced replacement tools")
        else:
            self.advanced_tools_frame.pack(fill="x", pady=(3, 0))
            self.advanced_toggle.configure(text="▾  Hide advanced replacement tools")

    def _compact_path_row(self, parent, label, variable, command, hint=""):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, style="Panel.TLabel", width=18).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 7))
        ttk.Button(row, text="Browse…", command=command).pack(side="left")
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w", padx=(146, 0), pady=(0, 1))

    def _build_pc_tab(self):
        intro = ttk.LabelFrame(self.pc_tab, text="  PC version · Original SAAT stream workflow  ", padding=12)
        intro.pack(fill="x", pady=(0, 10))
        ttk.Label(intro, text=(
            "This tab runs the original PC SAAT stream utility (saat_stream.exe). "
            "It is separate from the PS2 PAK tools. Export a PC stream to OGG + stream_import.ini, "
            "edit/replace OGG files, then import to create a new stream and update TrakLkup.dat."
        ), wraplength=1000, justify="left").pack(anchor="w")
        self._compact_path_row(self.pc_tab, "PC stream file/folder", self.pc_stream_var, self._pc_browse_stream,
                               "Select a PC GTA SA audio/streams file (e.g. BEATS) or a stream file set supported by SAAT.")
        self._compact_path_row(self.pc_tab, "Export folder", self.pc_export_dir_var, self._pc_browse_export,
                               "SAAT creates a station subfolder containing OGG tracks and stream_import.ini.")
        self._compact_path_row(self.pc_tab, "Import INI", self.pc_import_ini_var, self._pc_browse_ini,
                               "Choose stream_import.ini generated by the Export button.")
        self._compact_path_row(self.pc_tab, "Target stream output", self.pc_target_stream_var, self._pc_browse_target,
                               "Use a new output filename to preserve the original PC stream.")
        self._compact_path_row(self.pc_tab, "TrakLkup.dat", self.pc_lookup_var, self._pc_browse_lookup,
                               "Import updates the lookup file; choose a COPY of audio/CONFIG/TrakLkup.dat.")
        buttons = ttk.Frame(self.pc_tab)
        buttons.pack(fill="x", pady=(12, 8))
        ttk.Button(buttons, text="EXPORT PC STREAM TO OGG", style="Accent.TButton", command=self.pc_export).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="IMPORT / REBUILD PC STREAM", style="Accent.TButton", command=self.pc_import).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Open export folder", command=lambda: self._open_path(self.pc_export_dir_var.get().strip(), "Choose an export folder first.")).pack(side="left")
        ttk.Label(self.pc_tab, textvariable=self.pc_status_var, style="Muted.TLabel", wraplength=1000).pack(anchor="w", pady=(5, 0))
        notes = ttk.LabelFrame(self.pc_tab, text="  Important  ", padding=10)
        notes.pack(fill="x", pady=(12, 0))
        ttk.Label(notes, text=(
            "PC SAAT stream import expects stereo Ogg Vorbis files. This uses the original SAAT Windows executable, "
            "so PC stream actions require Windows. It does not process PS2 .PAK archives. Always back up the target "
            "stream and lookup file; import updates the selected lookup file."
        ), wraplength=1000, justify="left").pack(anchor="w")

    def _pc_exe(self) -> Path:
        exe = Path(__file__).resolve().parent / "saat" / "saat_stream.exe"
        if not exe.is_file():
            raise FileNotFoundError("Bundled saat/saat_stream.exe was not found. Re-extract the complete application ZIP.")
        if sys.platform != "win32":
            raise RuntimeError("The bundled original SAAT executable is Windows-only. Run the PC SAAT tab on Windows.")
        return exe

    def _pc_browse_stream(self):
        p = filedialog.askopenfilename(title="Select PC GTA SA stream", filetypes=[("All files", "*.*")])
        if not p:
            p = filedialog.askdirectory(title="Or select a PC stream folder")
        if p: self.pc_stream_var.set(p)

    def _pc_browse_export(self):
        p = filedialog.askdirectory(title="Choose export directory")
        if p: self.pc_export_dir_var.set(p)

    def _pc_browse_ini(self):
        p = filedialog.askopenfilename(title="Select stream_import.ini", filetypes=[("Import INI", "*.ini"), ("All files", "*.*")])
        if p:
            self.pc_import_ini_var.set(p)
            # Derive a sensible target output name and export root from the INI location.
            if not self.pc_target_stream_var.get().strip():
                src = self.pc_stream_var.get().strip()
                if src:
                    sp = Path(src)
                    self.pc_target_stream_var.set(str(sp.with_name(sp.name + ".modded")))

    def _pc_browse_target(self):
        p = filedialog.asksaveasfilename(title="Save rebuilt PC stream as", defaultextension=".modded", filetypes=[("PC stream output", "*.*")])
        if p: self.pc_target_stream_var.set(p)

    def _pc_browse_lookup(self):
        p = filedialog.askopenfilename(title="Select COPY of TrakLkup.dat", filetypes=[("TrakLkup.dat", "*.*")])
        if p: self.pc_lookup_var.set(p)

    def pc_export(self):
        try:
            exe = self._pc_exe()
            stream_text = self.pc_stream_var.get().strip()
            out_text = self.pc_export_dir_var.get().strip()
            if not stream_text: raise ValueError("Select a PC stream file or folder.")
            if not out_text: raise ValueError("Choose an export folder.")
            stream = Path(stream_text)
            out = Path(out_text)
            if not stream.exists(): raise FileNotFoundError("Select an existing PC stream file or folder.")
            out.mkdir(parents=True, exist_ok=True)
            cmd = [str(exe), "-e", str(stream), str(out)]
            self._log("[PC SAAT] Export command: " + subprocess.list2cmdline(cmd))
            result = subprocess.run(cmd, cwd=str(exe.parent), capture_output=True, text=True, errors="replace", timeout=3600)
            self._log(result.stdout or "[PC SAAT] (no standard output)")
            if result.stderr: self._log(result.stderr)
            if result.returncode != 0: raise RuntimeError(f"saat_stream.exe exited with code {result.returncode}.")
            # Find generated import INI and prefill controls.
            inis = list(out.rglob("stream_import.ini"))
            if inis:
                self.pc_import_ini_var.set(str(inis[0]))
                if not self.pc_target_stream_var.get().strip():
                    self.pc_target_stream_var.set(str(stream.with_name(stream.name + ".modded")))
            self.pc_status_var.set(f"Export complete. Output: {out}")
            messagebox.showinfo("PC stream export complete", f"SAAT exported the stream.\n\nOutput: {out}" + (f"\nImport INI: {inis[0]}" if inis else "\nNo stream_import.ini was found; check the log."))
        except Exception as exc:
            self.pc_status_var.set("PC export failed — see Activity Log.")
            self._log("[PC SAAT ERROR] " + str(exc))
            messagebox.showerror("PC stream export failed", str(exc))

    def pc_import(self):
        try:
            exe = self._pc_exe()
            target = Path(self.pc_target_stream_var.get().strip())
            ini = Path(self.pc_import_ini_var.get().strip())
            lookup = Path(self.pc_lookup_var.get().strip())
            if not ini.is_file(): raise FileNotFoundError("Select the stream_import.ini generated by SAAT export.")
            if not lookup.is_file(): raise FileNotFoundError("Select a COPY of the PC game's TrakLkup.dat.")
            if not target.name: raise ValueError("Choose a target stream output filename.")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not messagebox.askyesno("Overwrite output?", f"This output already exists:\n{target}\n\nOverwrite it?"):
                    return
            if lookup.resolve() == Path(self.pc_lookup_var.get().strip()).resolve():
                if not messagebox.askyesno("Confirm lookup update", "SAAT updates the selected TrakLkup.dat during import. Make sure this is a backup copy. Continue?"):
                    return
            cmd = [str(exe), "-i", str(target), str(ini), str(lookup)]
            self._log("[PC SAAT] Import command: " + subprocess.list2cmdline(cmd))
            result = subprocess.run(cmd, cwd=str(exe.parent), capture_output=True, text=True, errors="replace", timeout=3600)
            self._log(result.stdout or "[PC SAAT] (no standard output)")
            if result.stderr: self._log(result.stderr)
            if result.returncode != 0: raise RuntimeError(f"saat_stream.exe exited with code {result.returncode}.")
            if not target.exists(): raise RuntimeError("SAAT returned success but the target stream file was not created.")
            self.pc_status_var.set(f"Import complete: {target}")
            messagebox.showinfo("PC stream import complete", f"Rebuilt PC stream:\n{target}\n\nUpdated lookup copy:\n{lookup}\n\nTest the output in a backed-up PC game folder.")
        except Exception as exc:
            self.pc_status_var.set("PC import failed — see Activity Log.")
            self._log("[PC SAAT ERROR] " + str(exc))
            messagebox.showerror("PC stream import failed", str(exc))

    def _build_log_tab(self):
        toolbar = ttk.Frame(self.log_tab)
        toolbar.pack(fill="x", pady=(0, 7))
        ttk.Label(toolbar, text="Run details", font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Button(toolbar, text="Clear log", command=self.clear_log).pack(side="right")
        frame = ttk.Frame(self.log_tab)
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(frame, wrap="word", bg="#0b100d", fg="#e9e1c9", insertbackground="#fff4d8", relief="flat", padx=10, pady=9, font=("Consolas", 9), state="disabled", highlightthickness=1, highlightbackground=self.colors["border"])
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ys.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")

    def _log(self, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _on_station_selected(self, _event=None):
        # Reset manual lookup grouping when the user changes stations.
        self.group_var.set("Auto-detect")
        self._station_changed()

    def _station_changed(self):
        value = self.station_var.get()
        filename = value.split(" — ", 1)[0].strip() if " — " in value else "RE.PAK"
        current_pak = self.pak_var.get().strip()
        if not current_pak or Path(current_pak).name.upper() in STATIONS:
            base = Path(current_pak).parent if current_pak else Path.cwd()
            candidate = base / filename
            if candidate.is_file() or current_pak:
                self.pak_var.set(str(candidate))
        self.project_state.set(f"Station: {STATIONS.get(filename, 'Custom PAK')}")
        if self.pak_var.get():
            pak = Path(self.pak_var.get())
            if not self.extract_var.get():
                self.extract_var.set(str(pak.parent / f"{pak.stem}_extracted"))
            if not self.output_var.get():
                self.output_var.set(str(pak.parent / f"{pak.stem}_rebuilt"))

    def _browse_pak(self):
        p = filedialog.askopenfilename(title="Select PS2 radio PAK", filetypes=[("Radio PAK", "*.PAK *.pak"), ("All files", "*.*")])
        if p:
            self.last_result = None
            self.last_tracks = []
            self.detected_group = None
            self.pak_var.set(p)
            name = Path(p).name.upper()
            canonical = name[4:] if name.startswith("NEW-") else name
            for fname, station in STATIONS.items():
                if fname == canonical:
                    self.station_var.set(f"{fname} — {station}")
                    if name.startswith("NEW-"):
                        self.group_var.set(f"0x{core.KNOWN_ARCHIVE_IDS[fname]:02X}")
                    else:
                        self.group_var.set("Auto-detect")
                    break
            pak = Path(p)
            self.extract_var.set(str(pak.parent / f"{pak.stem}_extracted"))
            self.output_var.set(str(pak.parent / f"{pak.stem}_rebuilt"))
            self._station_changed()
            self._log(f"Selected PAK: {p}")

    def _browse_lookup(self):
        p = filedialog.askopenfilename(title="Select matching TRAKLKUP.DAT", filetypes=[("Lookup table", "*.DAT *.dat"), ("All files", "*.*")])
        if p:
            self.last_result = None
            self.last_tracks = []
            self.detected_group = None
            self.lookup_var.set(p)
            self._log(f"Selected lookup table: {p}")

    def _browse_extract(self):
        p = filedialog.askdirectory(title="Choose extracted tracks folder")
        if p:
            self.extract_var.set(p)
            self.refresh_track_list()

    def _browse_output(self):
        p = filedialog.askdirectory(title="Choose output folder")
        if p: self.output_var.set(p)

    def _browse_ffmpeg(self):
        p = filedialog.askopenfilename(title="Select ffmpeg executable", filetypes=[("FFmpeg executable", "ffmpeg.exe"), ("All files", "*.*")])
        if p: self.ffmpeg_var.set(p)

    def _paths(self):
        p_text, l_text = self.pak_var.get().strip().strip('"'), self.lookup_var.get().strip().strip('"')
        if not p_text or not Path(p_text).is_file():
            raise core.FormatError("Choose an existing PS2 radio .PAK file.")
        if not l_text or not Path(l_text).is_file():
            raise core.FormatError("Choose the matching AUDIO/CONFIG/TRAKLKUP.DAT file.")
        return Path(p_text), Path(l_text)

    def _settings(self):
        return self.group_var.get(), self.offset_var.get(), self.size_var.get()

    def inspect(self):
        try:
            pak_path, lookup_path = self._paths()
            result = core.inspect_archive(pak_path, lookup_path, *self._settings())
            pak, lookup_data, all_records, gid, off_unit, size_unit, tracks, stats = result
            self.last_result = result
            self.last_tracks = tracks
            self.detected_group = gid
            if self.offset_var.get() == "Auto-detect": self.offset_var.set(off_unit)
            if self.size_var.get() == "Auto-detect": self.size_var.set(size_unit)
            self.group_var.set(f"0x{gid:02X}")
            # Correct the displayed station using the PS2 lookup table, even if the
            # selected PAK filename is custom or has the wrong station name.
            canonical_name = core.ARCHIVE_FILENAME_BY_ID.get(gid)
            if canonical_name in STATIONS:
                self.station_var.set(f"{canonical_name} — {STATIONS[canonical_name]}")
            for item in self.track_tree.get_children():
                self.track_tree.delete(item)
            for tr in tracks:
                base_name = f"entry_{tr.record.index:04d}"
                extract_folder = Path(self.extract_var.get()) if self.extract_var.get() else None
                vag_path = extract_folder / f"{base_name}.vag" if extract_folder else None
                bin_path = extract_folder / f"{base_name}.bin" if extract_folder else None
                if vag_path and vag_path.is_file():
                    filename, fpath = vag_path.name, vag_path
                elif bin_path and bin_path.is_file():
                    filename, fpath = bin_path.name, bin_path
                else:
                    ext = ".vag" if tr.is_vag else ".bin"
                    filename = f"{base_name}{ext}"
                    fpath = extract_folder / filename if extract_folder else None
                size = fpath.stat().st_size if fpath and fpath.is_file() else tr.exact_size or tr.stored_size_bytes
                self.track_tree.insert("", "end", iid=str(tr.record.index), values=(
                    f"{tr.record.index:04d}", filename, f"{tr.offset_bytes:,}", human_size(size),
                    "VAGp" if tr.is_vag else "GTA SA stream" if tr.has_stream_header else "Raw / unknown", f"{tr.sample_rate:,} Hz" if tr.sample_rate else "—"
                ))
            self.project_state.set(f"ID 0x{gid:02X} · {len(tracks)} entries")
            vag_count = sum(t.is_vag for t in tracks)
            stream_count = sum(t.has_stream_header for t in tracks)
            if stream_count or vag_count:
                self.status_var.set(
                    f"Inspection OK — {stream_count} GTA SA stream headers, {vag_count} VAGp headers across {len(tracks)} entries."
                )
            else:
                self.status_var.set(f"Inspection OK — {len(tracks)} entries; unrecognized/raw mode.")
            self._log("=" * 84)
            self._log(f"INSPECT: {pak_path} ({human_size(len(pak))})")
            self._log(f"LOOKUP:  {lookup_path} ({human_size(len(lookup_data))}, {len(all_records):,} records)")
            self._log(f"Archive ID: 0x{gid:02X} · Station name from lookup: {canonical_name or 'Custom PAK'} · Offsets: {off_unit} · Sizes: {size_unit}")
            self._log(
                f"Entries in this PAK group: {len(tracks)} · GTA SA stream headers: {stream_count} · VAGp headers: {vag_count}"
            )
            if canonical_name and Path(pak_path).name.upper() != canonical_name:
                self._log(f"Filename normalization: rebuild output will be NEW-{canonical_name} based on lookup ID 0x{gid:02X}.")
            if stream_count:
                messagebox.showinfo(
                    "PS2 stream archive detected",
                    f"Detected archive ID 0x{gid:02X}.\n{len(tracks)} lookup entries found; "
                    f"{stream_count} GTA SA stream headers and {vag_count} VAGp headers detected.\n\n"
                    "This radio PAK uses GTA SA stream headers, not standalone VAGp files. That is normal; "
                    "the audio payload is stored after each 8,068-byte stream header. Continue with Extract tracks."
                )
            elif vag_count:
                messagebox.showinfo("Inspection complete", f"Detected archive ID 0x{gid:02X}.\n{len(tracks)} lookup entries found; {vag_count} have VAGp headers.\n\nCheck the Track browser tab for entry details.")
            else:
                self._log("NOTE: No VAGp or GTA SA stream signature was found at the selected entries. Confirm that the PAK and lookup table match and try setting the archive ID/offset unit manually.")
                messagebox.showwarning("Unrecognized/raw entries", f"Detected archive ID 0x{gid:02X}.\n{len(tracks)} lookup entries were found, but no VAGp or GTA SA stream headers were recognized.\n\nThe files may still be raw data, but audio transcoding is disabled until the format is identified. Confirm the PAK and lookup table are from the same PS2 release.")
        except Exception as exc:
            self.status_var.set("Inspection failed — see Activity log.")
            self._log("INSPECTION ERROR: " + str(exc))
            messagebox.showerror("Inspection failed", str(exc))

    def extract(self):
        try:
            pak, lookup = self._paths()
            folder_text = self.extract_var.get().strip()
            if not folder_text:
                folder_text = str(pak.parent / f"{pak.stem}_extracted")
                self.extract_var.set(folder_text)
            out_dir = Path(folder_text)
            if out_dir.exists() and any(out_dir.iterdir()):
                if not messagebox.askyesno("Folder not empty", f"This folder already contains files:\n{out_dir}\n\nMatching extracted files may be replaced. Continue?"):
                    return
            ok, skipped, off_unit, size_unit = core.extract_tracks(pak, lookup, out_dir, *self._settings())
            self.offset_var.set(off_unit); self.size_var.set(size_unit)
            self.refresh_track_list()
            self.tabs.select(self.browser_tab)
            self._log(f"EXTRACT COMPLETE: {ok} entries exported to {out_dir}")
            self.status_var.set(f"Extracted {ok} entries to {out_dir}")
            messagebox.showinfo("Extraction complete", f"Exported {ok} entries to:\n{out_dir}\n\nFiles are named entry_XXXX.vag or entry_XXXX.bin. Keep names and formats unchanged.")
        except Exception as exc:
            self.status_var.set("Extraction failed — see Activity log.")
            self._log("EXTRACTION ERROR: " + str(exc))
            messagebox.showerror("Extraction failed", str(exc))

    def refresh_track_list(self):
        folder = Path(self.extract_var.get().strip()) if self.extract_var.get().strip() else None
        for item in self.track_tree.get_children():
            self.track_tree.delete(item)
        result = self.last_result
        if result is None:
            try:
                if folder and folder.is_dir() and (folder / "manifest.json").is_file():
                    import json
                    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                    self._log(f"Loaded manifest: {len(manifest.get('tracks', []))} exported entries")
                    for item in manifest.get("tracks", []):
                        filename = item.get("file", "")
                        fpath = folder / filename
                        self.track_tree.insert("", "end", iid=str(item.get("table_record", filename)), values=(
                            str(item.get('table_record', '????')).zfill(4), filename,
                            f"{item.get('original_offset_bytes', 0):,}",
                            human_size(fpath.stat().st_size if fpath.is_file() else item.get("original_exact_size")),
                            "VAGp" if item.get("is_vagp") else "Raw / unknown", "—"
                        ))
            except Exception as exc:
                self._log(f"Could not read extraction manifest: {exc}")
            return
        tracks = result[6]
        for tr in tracks:
            base_name = f"entry_{tr.record.index:04d}"
            vag_path = folder / f"{base_name}.vag" if folder else None
            bin_path = folder / f"{base_name}.bin" if folder else None
            if vag_path and vag_path.is_file():
                filename, fpath = vag_path.name, vag_path
            elif bin_path and bin_path.is_file():
                filename, fpath = bin_path.name, bin_path
            else:
                ext = ".vag" if tr.is_vag else ".bin"
                filename = f"{base_name}{ext}"
                fpath = folder / filename if folder else None
            if fpath and fpath.is_file():
                size = fpath.stat().st_size
                status = "Extracted"
            else:
                size = tr.exact_size or tr.stored_size_bytes
                status = "VAGp" if tr.is_vag else "GTA SA stream" if tr.has_stream_header else "Raw / unknown"
            self.track_tree.insert("", "end", iid=str(tr.record.index), values=(f"{tr.record.index:04d}", filename, f"{tr.offset_bytes:,}", human_size(size), status, f"{tr.sample_rate:,} Hz" if tr.sample_rate else "—"))

    def _on_audio_drop(self, event):
        """Receive one or more source-audio files dropped on the Track Browser."""
        try:
            paths = [Path(p) for p in self.tk.splitlist(event.data)]
            if event.widget is self.track_tree:
                row = self.track_tree.identify_row(event.y)
                if row:
                    self.track_tree.selection_set(row)
                    self.track_tree.focus(row)
            self._start_audio_import(paths)
        except Exception as exc:
            self._log("AUDIO DROP ERROR: " + str(exc))
            messagebox.showerror("Audio drop failed", str(exc))
        return "copy"

    def pick_audio_for_tracks(self):
        """File-picker fallback and multi-file import for the Track Browser."""
        paths = filedialog.askopenfilenames(
            title="Choose replacement audio (select a starting track first)",
            filetypes=[
                ("Audio files", "*.wav *.wave *.mp3 *.flac *.ogg *.oga *.opus *.m4a *.aac *.wma *.aiff *.aif *.ape *.mp2 *.ac3 *.at3 *.at3p *.caf *.mp4 *.webm *.mkv *.mov"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            try:
                self._start_audio_import([Path(p) for p in paths])
            except Exception as exc:
                self._log("AUDIO IMPORT REQUEST ERROR: " + str(exc))
                messagebox.showerror("Cannot import audio", str(exc))

    def _start_audio_import(self, paths):
        if self._audio_import_busy:
            messagebox.showinfo("Conversion in progress", "Wait for the current audio conversion to finish before starting another.")
            return
        paths = [Path(p) for p in paths if Path(p).is_file()]
        if not paths:
            raise core.FormatError("No existing audio files were supplied.")
        if not self.last_tracks:
            raise core.FormatError("Inspect the PAK first, then extract tracks before dropping replacement audio.")
        folder_text = self.extract_var.get().strip()
        if not folder_text or not Path(folder_text).is_dir():
            raise core.FormatError("Extract the PAK first. Audio replacements must be written into the active extracted-track folder used by Rebuild.")
        tracks_dir = Path(folder_text)
        if not (tracks_dir / "manifest.json").is_file():
            raise core.FormatError("The selected folder has no manifest.json. Use Extract tracks and choose that output folder so the rebuild uses the same files.")

        selected = self.track_tree.selection()
        if not selected:
            raise core.FormatError("Select the first row that should receive audio, then drop the file(s) again.")
        visual_ids = list(self.track_tree.get_children())
        try:
            start_at = visual_ids.index(selected[0])
        except ValueError as exc:
            raise core.FormatError("The selected row is not part of the current Track Browser. Inspect the archive again.") from exc
        if start_at + len(paths) > len(visual_ids):
            raise core.FormatError(
                f"You dropped {len(paths)} file(s), but only {len(visual_ids) - start_at} track row(s) remain from the selected starting row. "
                "Select an earlier row or drop fewer files."
            )

        track_by_id = {tr.record.index: tr for tr in self.last_tracks}
        targets = []
        for n, source in enumerate(paths):
            record_id = int(visual_ids[start_at + n])
            tr = track_by_id.get(record_id)
            if tr is None:
                raise core.FormatError(f"Could not resolve lookup record {record_id} to the inspected archive.")
            if tr.has_stream_header:
                target = tracks_dir / f"entry_{record_id:04d}.bin"
                hdr = tracks_dir / f"entry_{record_id:04d}.hdr"
                if not hdr.is_file() or hdr.stat().st_size != tr.stream_header_size:
                    raise core.FormatError(
                        f"{hdr.name} is missing or invalid. Re-extract the archive before replacing track {record_id}."
                    )
            elif tr.is_vag:
                target = tracks_dir / f"entry_{record_id:04d}.vag"
            else:
                raise core.FormatError(
                    f"Lookup record {record_id} is an opaque raw entry, not a recognized PS2 stream/VAG track. "
                    "Audio transcoding is disabled for this entry so it cannot corrupt unknown data."
                )
            if not target.is_file():
                raise core.FormatError(f"Extracted track file is missing: {target.name}. Click Extract tracks again before replacing audio.")
            targets.append((source, tr, target))

        ffmpeg = self.ffmpeg_var.get().strip() or shutil.which("ffmpeg") or ""
        if not audio_encoder.find_ffmpeg(ffmpeg):
            raise core.FormatError("FFmpeg was not found. Install FFmpeg and set its executable in the Audio Preparation tab.")

        self._audio_import_busy = True
        self._busy = True
        self._audio_cancel_event = threading.Event()
        self.audio_progress.configure(value=0)
        self.audio_progress_text.set(f"Preparing {len(paths)} audio file(s)…")
        self.cancel_audio_button.configure(state="normal")
        self.status_var.set(f"Preparing to convert {len(paths)} audio file(s) to PS2 ADPCM…")
        self._log(f"AUDIO IMPORT START: {len(paths)} source file(s) → {tracks_dir}; start record {targets[0][1].record.index:04d}")
        self.drop_label.configure(text=f"Conversion queued: {len(paths)} audio file(s). Progress is shown below.")
        cancel_event = self._audio_cancel_event

        def report(message, percent=None):
            # Called from worker threads; marshal all widget updates to Tk's event loop.
            self.after(0, self._update_audio_progress, message, percent)

        def worker():
            try:
                result = self._encode_and_replace_files(tracks_dir, targets, ffmpeg, progress=report, cancel_event=cancel_event)
                self.after(0, self._finish_audio_import, result, None)
            except Exception as exc:
                self.after(0, self._finish_audio_import, None, f"{exc}\n\n{traceback.format_exc()}")

        threading.Thread(target=worker, name="SAAT-PS2-audio-import", daemon=True).start()

    def _update_audio_progress(self, message: str, percent=None):
        try:
            self.audio_progress_text.set(message)
            if percent is not None:
                self.audio_progress.configure(value=max(0, min(100, float(percent))))
            self.status_var.set(message)
        except (tk.TclError, AttributeError):
            pass

    def cancel_audio_import(self):
        event = self._audio_cancel_event
        if self._audio_import_busy and event is not None:
            event.set()
            self.audio_progress_text.set("Cancellation requested — stopping the current file safely…")
            self.status_var.set("Cancellation requested — stopping the current file safely…")
            self.cancel_audio_button.configure(state="disabled")
            self._log("AUDIO IMPORT: user requested cancellation.")

    @staticmethod
    def _encode_and_replace_files(tracks_dir: Path, targets, ffmpeg: str, progress=None, cancel_event=None):
        """Stage game-ready PS2 stream files and metadata before committing."""
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = tracks_dir / "_saatps2_backups" / stamp
        committed = []
        results = []
        with tempfile.TemporaryDirectory(prefix=".saatps2_staging_", dir=tracks_dir) as td:
            stage = Path(td)
            staged_targets = []
            total = len(targets)
            for n, (source, tr, target) in enumerate(targets):
                if cancel_event is not None and cancel_event.is_set():
                    raise audio_encoder.AudioEncodeError("Conversion cancelled by user; no replacements were committed.")
                if source.suffix.lower() not in audio_encoder.SUPPORTED_AUDIO_SUFFIXES:
                    raise core.FormatError(f"Unsupported audio extension: {source.name}")
                rate = tr.sample_rate or 24000
                raw_path = stage / f"encoded_{n:04d}.adpcm"
                base_percent = (n * 100.0) / max(total, 1)
                span_percent = 100.0 / max(total, 1)
                if progress:
                    progress(f"Track {n + 1}/{total}: {source.name} — starting…", base_percent)

                def track_progress(message, n=n, source=source, base_percent=base_percent, span_percent=span_percent):
                    pct = None
                    if message.startswith("Encoding ") and message.endswith("%"):
                        try:
                            fraction = float(message.split()[1].rstrip("%")) / 100.0
                            pct = base_percent + span_percent * fraction * 0.82
                        except (ValueError, IndexError):
                            pct = base_percent
                    else:
                        pct = base_percent
                    if progress:
                        progress(f"Track {n + 1}/{total}: {source.name} — {message}", pct)

                meta = audio_encoder.convert_audio_to_ps2_payload(
                    source, raw_path, ffmpeg, rate, progress=track_progress, cancel_event=cancel_event
                )
                if not raw_path.is_file() or raw_path.stat().st_size == 0:
                    raise core.FormatError(f"Encoder produced no payload for {source.name}.")

                header_stage = None
                header_target = None
                if tr.has_stream_header:
                    mini_path = stage / f"mini_{n:04d}.adpcm"
                    if progress:
                        progress(
                            f"Track {n + 1}/{total}: {source.name} — encoding 750 Hz mini stream",
                            base_percent + span_percent * 0.84,
                        )
                    mini_meta = audio_encoder.convert_audio_to_ps2_payload(
                        source, mini_path, ffmpeg, audio_encoder.GTASA_MINI_RATE,
                        progress=None, cancel_event=cancel_event
                    )
                    stage_file = stage / target.name
                    packed_meta = audio_encoder.pack_gtasa_ps2_stream_payload(raw_path, mini_path, stage_file)

                    # For type-4 streams the four size fields are per-channel
                    # unpadded lengths. Leaving the old lengths in place causes
                    # the game to interpret a new-duration stream using stale
                    # source metadata. Do not guess at unrelated loop/beat data.
                    header_target = tracks_dir / f"entry_{tr.record.index:04d}.hdr"
                    if not header_target.is_file():
                        raise core.FormatError(
                            f"Missing {header_target.name}; re-extract this PAK so its original stream header can be updated safely."
                        )
                    original_header = header_target.read_bytes()
                    header_bytes = audio_encoder.update_gtasa_type4_stream_header(
                        original_header, packed_meta, rate
                    )
                    header_stage = stage / header_target.name
                    header_stage.write_bytes(header_bytes)
                    meta.update({
                        "packed_bytes": packed_meta["packed_bytes"],
                        "chunk_count": packed_meta["chunk_count"],
                        "mini_sample_rate": audio_encoder.GTASA_MINI_RATE,
                        "mini_duration_seconds": mini_meta["duration_seconds"],
                        "full_channel_bytes": packed_meta["full_channel_bytes"],
                        "mini_channel_bytes": packed_meta["mini_channel_bytes"],
                        "encoder": "PSX ADPCM; GTA SA PS2 dual-stream chunk layout",
                    })
                else:
                    stage_file = stage / target.name
                    audio_encoder.wrap_vagp(raw_path, stage_file, rate)
                    core.read_vag_size(stage_file)

                staged_targets.append({
                    "stage_file": stage_file,
                    "target": target,
                    "header_stage": header_stage,
                    "header_target": header_target,
                    "source": source,
                    "track": tr,
                    "meta": meta,
                })
                if progress:
                    progress(f"Track {n + 1}/{total}: {source.name} — complete", ((n + 1) * 100.0) / max(total, 1))

            if cancel_event is not None and cancel_event.is_set():
                raise audio_encoder.AudioEncodeError("Conversion cancelled by user; no replacements were committed.")

            # Validate every target before backing up or committing anything.
            for item in staged_targets:
                if not item["target"].is_file():
                    raise core.FormatError(
                        f"Expected extracted target is missing: {item['target'].name}. Re-extract before replacing audio."
                    )
                if item["header_target"] is not None and not item["header_target"].is_file():
                    raise core.FormatError(f"Expected stream header is missing: {item['header_target'].name}.")

            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_by_target = {}
            for item in staged_targets:
                paths = [item["target"]]
                if item["header_target"] is not None:
                    paths.append(item["header_target"])
                for original in paths:
                    backup = backup_dir / f"{original.name}.original"
                    if backup.exists():
                        backup = backup_dir / f"{original.name}.{datetime.datetime.now().strftime('%H%M%S%f')}.original"
                    shutil.copy2(original, backup)
                    backup_by_target[str(original)] = backup

            try:
                for item in staged_targets:
                    os.replace(item["stage_file"], item["target"])
                    committed.append((item["target"], backup_by_target[str(item["target"])]))
                    if item["header_stage"] is not None:
                        os.replace(item["header_stage"], item["header_target"])
                        committed.append((item["header_target"], backup_by_target[str(item["header_target"])]))
                    meta = item["meta"]
                    results.append({
                        "source": str(item["source"]), "record": item["track"].record.index,
                        "target": str(item["target"]), "sample_rate": meta["sample_rate"],
                        "duration": meta["duration_seconds"], "bytes": item["target"].stat().st_size,
                        "encoder": meta.get("encoder", "PS2 ADPCM"),
                        "chunk_count": meta.get("chunk_count"),
                        "mini_sample_rate": meta.get("mini_sample_rate"),
                    })
            except Exception:
                for original, backup in reversed(committed):
                    if backup.is_file():
                        shutil.copy2(backup, original)
                raise
        return {"items": results, "backup_dir": str(backup_dir)}

    def _finish_audio_import(self, result, error):
        self._audio_import_busy = False
        self._busy = False
        self._audio_cancel_event = None
        self.cancel_audio_button.configure(state="disabled")
        self.drop_label.configure(
            text=("Drag WAV / MP3 / OGG / FLAC / AT3 audio here. Select a starting track first; multiple files fill subsequent rows."
                  if self.dnd_enabled else
                  "Drag-and-drop support is not installed. Use ‘Convert audio into selected track(s)…’ or install requirements.txt.")
        )
        if error:
            if "cancelled by user" in error.lower():
                self.status_var.set("Audio conversion cancelled.")
                self.audio_progress_text.set("Conversion cancelled. Original extracted tracks were left unchanged unless commit had begun.")
                self._log("AUDIO IMPORT CANCELLED:\n" + error)
                messagebox.showinfo("Conversion cancelled", "Audio conversion was cancelled. No files were committed if cancellation happened during encoding. Check the Activity Log for details.")
            else:
                self.status_var.set("Audio conversion failed — see Activity log.")
                self.audio_progress_text.set("Conversion failed. See Activity Log for details.")
                self._log("AUDIO IMPORT FAILED:\n" + error)
                messagebox.showerror("Audio conversion failed", error[-3500:])
            return
        self.audio_progress.configure(value=100)
        self.audio_progress_text.set(f"Finished: {len(result['items'])} replacement(s) encoded and written.")
        self.refresh_track_list()
        for item in result["items"]:
            self._log(
                f"AUDIO REPLACED: record {item['record']:04d}; {Path(item['source']).name} → "
                f"{Path(item['target']).name}; {item['sample_rate']} Hz; "
                f"{item['duration']:.2f}s; {item['bytes']:,} bytes; encoder={item.get('encoder', 'PS2 ADPCM')}"
                + (f"; chunks={item['chunk_count']}; mini={item['mini_sample_rate']} Hz" if item.get('chunk_count') else "")
            )
        self._log(f"Original track backups: {result['backup_dir']}")
        self.status_var.set(f"Encoded and replaced {len(result['items'])} track(s). Ready to rebuild and verify.")
        messagebox.showinfo(
            "Audio encoded and replaced",
            f"Converted and replaced {len(result['items'])} track(s).\n\n"
            f"Backups: {result['backup_dir']}\n\n"
            "The encoded files were written directly into the active extracted-track folder used by Rebuild. "
            "Next click Rebuild archive; the output will be checked by re-extracting and comparing the replacement data.",
        )

    def replace_selected(self):
        sel = self.track_tree.selection()
        if not sel:
            messagebox.showwarning("No entry selected", "Select an entry in the Track browser first.")
            return
        folder_text = self.extract_var.get().strip()
        if not folder_text or not Path(folder_text).is_dir():
            messagebox.showwarning("Extract first", "Extract the PAK before replacing individual entries.")
            return
        record_index = int(sel[0])
        tr = next((t for t in self.last_tracks if t.record.index == record_index), None)
        if tr is None:
            messagebox.showwarning("Inspect first", "Inspect the archive first to load the selected entry details.")
            return
        target_ext = ".vag" if tr.is_vag else ".bin"
        source = filedialog.askopenfilename(title="Select a replacement track with matching format", filetypes=[("VAG or raw PS2 data", "*.vag *.bin"), ("All files", "*.*")])
        if not source: return
        src = Path(source)
        if src.suffix.lower() != target_ext:
            messagebox.showerror("Format mismatch", f"Entry {record_index} expects {target_ext} based on its extracted form.\nSelected file: {src.name}\n\nConvert the audio to the matching PS2 format first; renaming isn't conversion.")
            return
        try:
            if target_ext == ".vag":
                core.read_vag_size(src)
            target = Path(folder_text) / f"entry_{record_index:04d}{target_ext}"
            if target.exists() and not messagebox.askyesno("Replace entry", f"Replace {target.name} with {src.name}?"):
                return
            shutil.copy2(src, target)
            self.refresh_track_list()
            self._log(f"REPLACED: lookup entry {record_index:04d} ← {src}")
            self.status_var.set(f"Replaced entry {record_index:04d}")
        except Exception as exc:
            messagebox.showerror("Replacement failed", str(exc))
            self._log("REPLACEMENT ERROR: " + str(exc))

    def import_folder(self):
        folder_text = self.extract_var.get().strip()
        if not folder_text or not Path(folder_text).is_dir():
            messagebox.showwarning("Extract first", "Extract the archive first, then import replacement files.")
            return
        source_dir_text = filedialog.askdirectory(title="Choose folder containing matching entry_XXXX.vag/.bin files")
        if not source_dir_text: return
        source_dir = Path(source_dir_text)
        dest_dir = Path(folder_text)
        copied, mismatched, ignored = 0, [], 0
        try:
            expected = {p.name.lower(): p for p in dest_dir.glob("entry_*.*") if p.is_file() and p.suffix.lower() in (".vag", ".bin")}
            for name, target in expected.items():
                candidate = source_dir / target.name
                if not candidate.is_file():
                    ignored += 1
                    continue
                if candidate.suffix.lower() != target.suffix.lower():
                    mismatched.append(target.name)
                    continue
                if target.suffix.lower() == ".vag":
                    core.read_vag_size(candidate)
                shutil.copy2(candidate, target)
                copied += 1
            self.refresh_track_list()
            msg = f"Imported {copied} replacement files.\nNo matching file: {ignored}.\nFormat mismatch: {len(mismatched)}."
            if mismatched:
                msg += "\n\nMismatched files:\n" + "\n".join(mismatched[:12])
            self._log(f"BATCH IMPORT: {msg.replace(chr(10), ' | ')}")
            messagebox.showinfo("Batch import complete", msg)
        except Exception as exc:
            self._log("BATCH IMPORT ERROR: " + str(exc))
            messagebox.showerror("Batch import failed", str(exc))

    def rebuild(self):
        try:
            pak, lookup = self._paths()
            folder_text = self.extract_var.get().strip()
            if not folder_text or not Path(folder_text).is_dir():
                raise core.FormatError("Choose an extracted tracks folder first. Use Extract tracks before rebuilding.")
            output_text = self.output_var.get().strip() or str(pak.parent / f"{pak.stem}_rebuilt")
            self.output_var.set(output_text)
            out_dir = Path(output_text)
            if not messagebox.askyesno("Rebuild archive", f"Create a new PAK and lookup table in:\n{out_dir}\n\nThe source files will not be overwritten. Continue?"):
                return
            pak_out, lookup_out, count, offset, size = core.rebuild_archive(pak, lookup, Path(folder_text), out_dir, *self._settings())
            self.offset_var.set(offset); self.size_var.set(size)
            self._log("=" * 84)
            self._log(f"REBUILD COMPLETE\nPAK: {pak_out}\nLookup: {lookup_out}\nEntries packed: {count}\nOffsets: {offset}; sizes: {size}")
            self.status_var.set(f"Rebuilt {count} entries — outputs saved in {out_dir}")
            self.tabs.select(self.browser_tab)
            messagebox.showinfo("Rebuild complete", f"Created both files:\n{pak_out}\n{lookup_out}\n\nUse them together. Test the rebuilt image in PCSX2 before using it elsewhere.")
        except Exception as exc:
            self.status_var.set("Rebuild failed — see Activity log.")
            self._log("REBUILD ERROR: " + str(exc))
            messagebox.showerror("Rebuild failed", str(exc))

    def auto_rename_files(self):
        if not self.last_tracks:
            messagebox.showwarning("Inspect first", "Load the PAK and matching TRAKLKUP.DAT, then click Inspect archive before auto-renaming files.")
            return
        current = self.extract_var.get().strip()
        initial = current if current and Path(current).is_dir() else str(Path(self.pak_var.get()).parent if self.pak_var.get() else Path.cwd())
        folder_text = filedialog.askdirectory(title="Choose the folder containing replacement PS2 track files", initialdir=initial)
        if not folder_text:
            return
        folder = Path(folder_text)
        try:
            plan = core.build_auto_rename_plan(folder, self.last_tracks)
            changes = [item for item in plan if str(Path(item["source"]).resolve()).casefold() != str(Path(item["target"]).resolve()).casefold()]
            if not changes:
                self.extract_var.set(str(folder))
                self.refresh_track_list()
                messagebox.showinfo("Filenames already match", f"All {len(plan)} supported files already use the names expected by the selected lookup table.")
                return
            sequence = [item for item in plan if item.get("method") != "lookup record index"]
            preview_lines = [f"{Path(item['source']).name}  →  {Path(item['target']).name}  (lookup record {item['record_index']:04d})" for item in changes[:18]]
            more = f"\n…plus {len(changes) - 18} more" if len(changes) > 18 else ""
            sequence_note = ""
            if sequence:
                sequence_note = (
                    f"\n\n{len(sequence)} file(s) have no matching table-record number. They will be assigned in natural filename order "
                    "to the unfilled records in lookup/physical order. Check this ordering carefully; filenames alone cannot reveal song identity."
                )
            prompt = (
                f"Normalize {len(changes)} filename(s) in:\n{folder}\n\n"
                + "\n".join(preview_lines) + more + sequence_note
                + "\n\nThe tool only renames files; it does not convert WAV/AT3/MP3 audio. Continue?"
            )
            if not messagebox.askyesno("Confirm automatic renaming", prompt):
                return
            changed = core.apply_auto_rename_plan(plan)
            self.extract_var.set(str(folder))
            self.refresh_track_list()
            self.status_var.set(f"Auto-renamed {changed} track file(s) using lookup table 0x{self.detected_group:02X}.")
            self._log(f"AUTO-RENAME: folder={folder}; selected archive ID=0x{self.detected_group:02X}; planned={len(plan)}; renamed={changed}")
            for item in changes:
                self._log(f"  record {item['record_index']:04d}: {Path(item['source']).name} -> {Path(item['target']).name} [{item['method']}]")
            messagebox.showinfo("Auto-rename complete", f"Renamed {changed} file(s).\n\nThe selected folder is now the active track folder. Review the Track Browser, then rebuild the PAK + TRAKLKUP.DAT pair.")
        except Exception as exc:
            self._log("AUTO-RENAME ERROR: " + str(exc))
            messagebox.showerror("Auto-rename failed", str(exc))

    def open_extract_folder(self):
        self._open_path(self.extract_var.get().strip(), "Choose an extracted tracks folder first.")

    def open_output_folder(self):
        self._open_path(self.output_var.get().strip(), "Choose an output folder first.")

    def _open_path(self, text, error):
        try:
            if not text:
                raise FileNotFoundError(error)
            reveal_path(Path(text))
        except Exception as exc:
            messagebox.showerror("Cannot open folder", str(exc))

    def _open_readme(self):
        path = Path(__file__).with_name("README.txt")
        try:
            if path.is_file():
                reveal_path(path)
            else:
                messagebox.showinfo("README", "See the README.txt file included in the downloaded package.")
        except Exception as exc:
            messagebox.showerror("Cannot open README", str(exc))

    def _about(self):
        messagebox.showinfo(APP_TITLE, "San Andreas Audio Toolbox PC/PS2 GUI\nPC tab runs the original SAAT stream utility; PS2 tab uses a separate PAK/lookup workflow.\n\nAlways back up game files and test rebuilt assets in the appropriate game/emulator.")


def main():
    if "--self-test" in sys.argv:
        core.run_self_test()
        audio_encoder.run_gtasa_stream_layout_self_test()
        print("GTA SA PS2 type-4 format self-test passed: chunk layout, channel first-frame flags, and header rate/size updates.")
        return
    app = Studio()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except tk.TclError as exc:
        print(f"GUI could not start: {exc}", file=sys.stderr)
        print("On Windows, use Launch_San_Andreas_Audio_Toolbox_PC_PS2_GUI.bat with Python 3 and Tkinter installed.", file=sys.stderr)
        raise

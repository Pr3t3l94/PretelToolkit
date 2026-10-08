"""
PretelToolkit - Herramienta de técnico post-formateo para Windows
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    BooleanVar,
    Canvas,
    Frame,
    Scrollbar,
    Text,
    Tk,
    Toplevel,
    messagebox,
    ttk,
)

APP_TITLE = "PretelToolkit"
APP_VERSION = "3.0.0"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "software.json"
LOGS_DIR = BASE_DIR / "logs"


@dataclass
class Preset:
    key: str
    name: str
    description: str
    program_ids: list[str]
    smart_gpu: bool = False


@dataclass
class Program:
    id: str
    name: str
    category: str
    description: str
    url: str
    filename: str
    install_args: list[str]
    requires_admin: bool = False
    gpu_filter: list[str] | None = None
    url_type: str | None = None
    recommended: bool = False
    portable: bool = False
    winget_id: str | None = None


@dataclass
class SystemInfo:
    os_name: str = "Windows"
    os_display: str = ""
    arch: str = ""
    cpu: str = ""
    ram_gb: float = 0.0
    gpus: list[str] = field(default_factory=list)
    disk_summary: str = ""
    internet: bool = False
    admin: bool = False


@dataclass
class InstallResult:
    name: str
    ok: bool
    detail: str = ""


_session_log: Path | None = None
_session_results: list[InstallResult] = []


def ensure_dirs() -> None:
    (BASE_DIR / "downloads").mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


def start_session_log() -> Path:
    global _session_log, _session_results
    ensure_dirs()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _session_log = LOGS_DIR / f"PretelToolkit_{stamp}.log"
    _session_results = []
    with _session_log.open("w", encoding="utf-8") as fh:
        fh.write(f"=== {APP_TITLE} v{APP_VERSION} ===\n")
        fh.write(f"Inicio: {datetime.now().isoformat(timespec='seconds')}\n\n")
    return _session_log


def log_message(message: str) -> None:
    ensure_dirs()
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    if _session_log is None:
        start_session_log()
    assert _session_log is not None
    with _session_log.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    with (LOGS_DIR / "setup.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def record_result(name: str, ok: bool, detail: str = "") -> None:
    _session_results.append(InstallResult(name=name, ok=ok, detail=detail))
    mark = "OK" if ok else "ERROR"
    log_message(f"RESULTADO [{mark}] {name}" + (f" — {detail}" if detail else ""))


def write_final_report() -> Path:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report = LOGS_DIR / f"Informe_{stamp}.txt"
    ok_n = sum(1 for r in _session_results if r.ok)
    fail_n = sum(1 for r in _session_results if not r.ok)
    lines = [
        f"{APP_TITLE} — Informe final",
        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Correctos: {ok_n}  |  Errores: {fail_n}",
        "",
        "Detalle:",
    ]
    for r in _session_results:
        mark = "[OK]" if r.ok else "[ERROR]"
        lines.append(f"  {mark} {r.name}" + (f" — {r.detail}" if r.detail else ""))
    if _session_log:
        lines.extend(["", f"Log completo: {_session_log.name}"])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_message(f"Informe guardado: {report.name}")
    return report


def is_admin() -> bool:
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    import ctypes

    params = " ".join(f'"{arg}"' for arg in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, str(BASE_DIR), 1
    )


def _run_hidden(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=timeout,
    )


def check_internet(timeout: float = 3.0) -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=timeout).close()
        return True
    except OSError:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
            return True
        except OSError:
            return False


def detect_gpu_names() -> list[str]:
    names: list[str] = []
    try:
        result = _run_hidden(["wmic", "path", "win32_VideoController", "get", "name"])
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower() == "name":
                continue
            names.append(line)
    except Exception:
        pass
    if names:
        return names
    try:
        ps_cmd = (
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
        )
        result = _run_hidden(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=30)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                names.append(line)
        return names
    except Exception:
        return names


def detect_disks() -> str:
    """Devuelve resumen tipo 'SSD · HDD' o 'SSD'."""
    kinds: set[str] = set()
    try:
        ps = (
            "$disks = Get-PhysicalDisk -ErrorAction SilentlyContinue; "
            "if ($disks) { $disks | ForEach-Object { $_.MediaType } } "
            "else { Get-CimInstance Win32_DiskDrive | ForEach-Object { "
            "if ($_.Model -match 'SSD|NVMe') {'SSD'} else {'HDD'} } }"
        )
        result = _run_hidden(["powershell", "-NoProfile", "-Command", ps], timeout=40)
        for line in result.stdout.splitlines():
            t = line.strip().upper()
            if "SSD" in t or "NVME" in t or t == "4":
                kinds.add("SSD")
            elif "HDD" in t or "UNSPECIFIED" in t or t == "3":
                kinds.add("HDD")
    except Exception:
        pass
    try:
        if not kinds:
            result = _run_hidden(["wmic", "diskdrive", "get", "model,mediatype"])
            text = result.stdout.lower()
            if "ssd" in text or "nvme" in text:
                kinds.add("SSD")
            if "hdd" in text or "fixed hard disk" in text:
                kinds.add("HDD")
            if not kinds and "model" in text:
                kinds.add("Disco")
        if not kinds:
            return "Desconocido"
        order = ["SSD", "HDD", "Disco"]
        return " · ".join(k for k in order if k in kinds)
    except Exception:
        return "Desconocido"


def detect_windows_display() -> str:
    try:
        ps = (
            "$o = Get-CimInstance Win32_OperatingSystem; "
            "'{0} (Build {1})' -f $o.Caption.Trim(), $o.BuildNumber"
        )
        result = _run_hidden(["powershell", "-NoProfile", "-Command", ps], timeout=25)
        line = result.stdout.strip().splitlines()
        if line:
            return line[0].strip()
    except Exception:
        pass
    try:
        ver = platform.version()
        build = int(ver.split(".")[2]) if ver.count(".") >= 2 else 0
        name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{name} (Build {build or '?'})"
    except Exception:
        return f"Windows {ver}"


def detect_system_info() -> SystemInfo:
    info = SystemInfo(
        os_name=platform.system(),
        os_display=detect_windows_display(),
        arch=platform.machine() or ("AMD64" if sys.maxsize > 2**32 else "x86"),
        gpus=detect_gpu_names(),
        disk_summary=detect_disks(),
        internet=check_internet(),
        admin=is_admin(),
    )
    try:
        try:
            result = _run_hidden(["wmic", "cpu", "get", "name"])
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and line.lower() != "name":
                    info.cpu = line
                    break
        except Exception:
            info.cpu = platform.processor() or "Desconocido"
        result = _run_hidden(["wmic", "computersystem", "get", "totalphysicalmemory"])
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                info.ram_gb = round(int(line) / (1024**3), 1)
                break
    except Exception:
        pass
    return info


def gpu_vendor_label(gpus: list[str]) -> str:
    text = " ".join(gpus).lower()
    found: list[str] = []
    if "nvidia" in text:
        found.append("NVIDIA")
    if "amd" in text or "radeon" in text:
        found.append("AMD")
    if "intel" in text:
        found.append("Intel")
    if found:
        return " / ".join(found)
    if gpus:
        return gpus[0]
    return "No detectada"


def gpu_matches_filter(gpu_filter: list[str] | None, gpu_names: list[str]) -> bool:
    if not gpu_filter:
        return True
    combined = " ".join(gpu_names).lower()
    return any(token in combined for token in gpu_filter)


def load_config() -> tuple[list[Program], list[Preset], Path]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No se encuentra la configuración: {CONFIG_PATH}")

    with CONFIG_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)

    download_dir = BASE_DIR / data.get("download_folder", "downloads")
    download_dir.mkdir(exist_ok=True)

    programs: list[Program] = []
    for item in data.get("programs", []):
        programs.append(
            Program(
                id=item["id"],
                name=item["name"],
                category=item.get("category", "General"),
                description=item.get("description", ""),
                url=item["url"],
                filename=item["filename"],
                install_args=item.get("install_args", []),
                requires_admin=item.get("requires_admin", False),
                gpu_filter=item.get("gpu_filter"),
                url_type=item.get("url_type"),
                recommended=item.get("recommended", False),
                portable=item.get("portable", False),
                winget_id=item.get("winget_id"),
            )
        )

    presets: list[Preset] = []
    for key, preset in data.get("presets", {}).items():
        presets.append(
            Preset(
                key=key,
                name=preset.get("name", key),
                description=preset.get("description", ""),
                program_ids=preset.get("programs", []),
                smart_gpu=preset.get("smart_gpu", False),
            )
        )

    return programs, presets, download_dir


def winget_available() -> bool:
    try:
        r = _run_hidden(["winget", "--version"], timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def install_via_winget(winget_id: str) -> int:
    cmd = [
        "winget",
        "install",
        "--id",
        winget_id,
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent",
        "--disable-interactivity",
    ]
    log_message(f"winget: {' '.join(cmd)}")
    completed = subprocess.run(
        cmd, creationflags=subprocess.CREATE_NO_WINDOW, timeout=3600
    )
    # 0x8A15002B = ya instalado / sin actualización; 0x8A150061 = paquete ya instalado
    if (completed.returncode & 0xFFFFFFFF) in (2316632107, 2316632161):
        log_message("winget: ya estaba instalado y actualizado.")
        return 0
    return completed.returncode


def resolve_adobe_reader_url(page_url: str) -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        page_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PretelToolkit/3.0"
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
        html = response.read().decode("utf-8", errors="ignore")
    match = re.search(r"https://[^\"']+Reader[^\"']+\.exe", html, re.IGNORECASE)
    if match:
        return match.group(0)
    raise RuntimeError("No se pudo encontrar el enlace de Adobe Reader.")


def resolve_download_url(program: Program) -> str:
    if program.url_type == "adobe_reader":
        return resolve_adobe_reader_url(program.url)
    if program.url_type == "malwarebytes":
        return "https://data-cdn.mbamupdates.com/web/mb4-setup-consumer/offline/MBSetup.exe"
    if program.url_type == "manual_download":
        raise RuntimeError(f"{program.name}: descarga manual requerida.")
    return program.url


def download_file(
    url: str,
    destination: Path,
    progress_cb,
    cancel_event: threading.Event,
) -> None:
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PretelToolkit/3.0"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, context=ctx, timeout=120) as response:
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            with destination.open("wb") as out:
                while True:
                    if cancel_event.is_set():
                        raise RuntimeError("Descarga cancelada por el usuario.")
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        progress_cb(int(done * 100 / total), done, total)
                    else:
                        progress_cb(-1, done, 0)
    except (urllib.error.URLError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        curl = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "curl.exe")
        if not os.path.exists(curl):
            raise
        log_message("Certificado no reconocido por Python; reintentando con curl.exe de Windows...")
        proc = subprocess.Popen(
            [curl, "-L", "--fail", "-s", "-S", "-A", user_agent, "-o", str(destination), url],
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel_event.is_set():
                    proc.kill()
                    proc.wait()
                    raise RuntimeError("Descarga cancelada por el usuario.")
                size = destination.stat().st_size if destination.exists() else 0
                progress_cb(-1, size, 0)
        if proc.returncode != 0:
            err = proc.stderr.read().decode("utf-8", "ignore").strip()
            raise RuntimeError(f"curl.exe falló (código {proc.returncode}): {err}")

    suffix = destination.suffix.lower()
    try:
        with destination.open("rb") as f:
            head = f.read(8)
        valid = True
        if suffix == ".exe":
            valid = head.startswith(b"MZ")
        elif suffix == ".msi":
            valid = head.startswith(b"\xd0\xcf\x11\xe0")
        if not valid:
            destination.unlink()
            raise RuntimeError(
                "El enlace no ha devuelto un instalador (parece una página web). "
                "Revisa la 'url' de este programa en software.json."
            )
    except OSError:
        pass


def build_install_command(installer: Path, args: list[str]) -> list[str]:
    if installer.suffix.lower() == ".msi":
        return ["msiexec", "/i", str(installer), *args]
    return [str(installer), *args]


def run_installer(installer: Path, args: list[str], requires_admin: bool) -> int:
    command = build_install_command(installer, args)
    log_message(f"Ejecutando: {' '.join(command)}")

    if requires_admin and not is_admin():
        import ctypes

        if installer.suffix.lower() == ".msi":
            exe = "msiexec"
            params = " ".join(f'"{arg}"' for arg in command[1:])
        else:
            exe = str(installer)
            params = " ".join(f'"{arg}"' for arg in args)
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if result <= 32:
            raise RuntimeError(f"No se pudo elevar permisos (código {result}).")
        return 0

    completed = subprocess.run(
        command,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=3600,
    )
    return completed.returncode


def trigger_windows_update() -> str:
    """Lanza Windows Update (usa UsoClient / Settings)."""
    try:
        subprocess.Popen(
            ["start", "ms-settings:windowsupdate"],
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        _run_hidden(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "try { UsoClient StartInteractiveScan } catch { Start-Process ms-settings:windowsupdate }",
            ],
            timeout=60,
        )
        return "Windows Update abierto / escaneo iniciado"
    except Exception as exc:
        return f"No se pudo lanzar Windows Update: {exc}"


class SetupPCApp:
    def __init__(self) -> None:
        start_session_log()
        self.root = Tk()
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1040x760")
        self.root.minsize(920, 640)
        self._set_window_icon()

        self.programs, self.presets, self.download_dir = load_config()
        self.system_info = detect_system_info()
        self.gpu_names = self.system_info.gpus
        self.vars: dict[str, BooleanVar] = {}
        self.running = False
        self.cancel_event = threading.Event()
        self.prefer_winget = BooleanVar(value=winget_available())

        self._build_ui()
        self._log_startup()

    def _set_window_icon(self) -> None:
        icon_path = BASE_DIR / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except Exception:
                pass
        png_path = BASE_DIR / "assets" / "icon.png"
        if png_path.exists():
            try:
                from tkinter import PhotoImage

                self._icon_img = PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self._icon_img)
            except Exception:
                return

    def _log_startup(self) -> None:
        info = self.system_info
        self.append_log(f"Iniciado {APP_TITLE} v{APP_VERSION}")
        self.append_log(f"Windows: {info.os_display} · {info.arch}")
        self.append_log(f"CPU: {info.cpu or '—'}")
        self.append_log(f"RAM: {info.ram_gb} GB" if info.ram_gb else "RAM: —")
        self.append_log(f"GPU: {gpu_vendor_label(info.gpus)}")
        if info.gpus:
            for g in info.gpus:
                self.append_log(f"  · {g}")
        self.append_log(f"Disco: {info.disk_summary}")
        self.append_log(f"Internet: {'conectado' if info.internet else 'SIN CONEXIÓN'}")
        self.append_log(f"Admin: {'sí' if info.admin else 'no'}")
        self.append_log(f"winget: {'disponible' if winget_available() else 'no disponible'}")
        if _session_log:
            self.append_log(f"Log: {_session_log.name}")

    def _build_scrollable_list(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent)
        container.pack(fill=BOTH, expand=True)

        canvas = Canvas(container, highlightthickness=0)
        scrollbar = Scrollbar(container, orient=VERTICAL, command=canvas.yview)
        self.list_inner = ttk.Frame(canvas)

        self.list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.list_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        categories: dict[str, list[Program]] = {}
        for program in self.programs:
            categories.setdefault(program.category, []).append(program)

        row = 0
        for category in sorted(categories.keys()):
            ttk.Label(
                self.list_inner, text=category, font=("Segoe UI", 11, "bold")
            ).grid(row=row, column=0, sticky="w", pady=(10, 4), padx=4)
            row += 1
            for program in categories[category]:
                var = BooleanVar(value=False)
                self.vars[program.id] = var
                item = ttk.Frame(self.list_inner)
                item.grid(row=row, column=0, sticky="w", padx=(12, 0))
                ttk.Checkbutton(item, text=program.name, variable=var).pack(side=LEFT)

                tags: list[str] = []
                if program.winget_id:
                    tags.append("auto-update")
                if program.recommended:
                    tags.append("recomendado")
                if program.gpu_filter:
                    gpu_ok = gpu_matches_filter(program.gpu_filter, self.gpu_names)
                    tags.append("[GPU detectada]" if gpu_ok else "[otra GPU]")
                if tags:
                    color = "#006400" if any("detectada" in t for t in tags) else "#555555"
                    ttk.Label(
                        item, text="  " + " · ".join(tags), foreground=color
                    ).pack(side=LEFT)
                row += 1
                if program.description:
                    ttk.Label(
                        self.list_inner,
                        text=f"      {program.description}",
                        foreground="#555555",
                        wraplength=880,
                    ).grid(row=row, column=0, sticky="w", padx=(28, 8))
                    row += 1

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=BOTH)

        ttk.Label(
            header,
            text="PretelToolkit — Herramienta de técnico post-formateo",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")

        detect = ttk.LabelFrame(self.root, text="PC detectado", padding=(10, 8))
        detect.pack(fill=BOTH, padx=10, pady=(0, 6))

        info = self.system_info
        lines = [
            f"Windows: {info.os_display}  ·  {info.arch}",
            f"CPU: {info.cpu or '—'}",
            f"RAM: {info.ram_gb} GB" if info.ram_gb else "RAM: —",
            f"GPU: {gpu_vendor_label(info.gpus)}",
            f"Disco: {info.disk_summary}",
            f"Internet: {'conectado' if info.internet else 'SIN CONEXIÓN'}"
            + ("  ·  Admin" if info.admin else "  ·  Sin admin"),
        ]
        ttk.Label(
            detect, text="\n".join(lines), font=("Segoe UI", 9), justify=LEFT
        ).pack(anchor="w")

        toolbar = ttk.Frame(self.root, padding=(10, 4))
        toolbar.pack(fill=BOTH)
        ttk.Button(toolbar, text="Seleccionar todo", command=self.select_all).pack(
            side=LEFT, padx=(0, 5)
        )
        ttk.Button(toolbar, text="Quitar todo", command=self.select_none).pack(
            side=LEFT, padx=(0, 5)
        )
        ttk.Button(toolbar, text="Detectar de nuevo", command=self.refresh_system).pack(
            side=LEFT, padx=(0, 5)
        )
        ttk.Button(toolbar, text="Editar lista", command=self.open_config_info).pack(
            side=LEFT
        )
        if not is_admin():
            ttk.Button(
                toolbar, text="Ejecutar como admin", command=self.request_admin
            ).pack(side=RIGHT)

        if self.presets:
            preset_bar = ttk.LabelFrame(
                self.root, text="Perfiles de instalación", padding=(10, 6)
            )
            preset_bar.pack(fill=BOTH, padx=10, pady=(0, 6))
            for preset in self.presets:
                ttk.Button(
                    preset_bar,
                    text=preset.name,
                    command=lambda p=preset: self.apply_preset(p),
                ).pack(side=LEFT, padx=(0, 6))

        opts = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        opts.pack(fill=BOTH)
        ttk.Checkbutton(
            opts,
            text="Usar winget si está disponible (descarga siempre la última versión)",
            variable=self.prefer_winget,
        ).pack(side=LEFT)

        body = ttk.Panedwindow(self.root, orient="vertical")
        body.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        list_frame = ttk.LabelFrame(body, text="Programas y drivers", padding=6)
        body.add(list_frame, weight=3)
        self._build_scrollable_list(list_frame)

        log_frame = ttk.LabelFrame(body, text="Progreso y registro", padding=8)
        body.add(log_frame, weight=2)

        self.progress = ttk.Progressbar(log_frame, mode="determinate", maximum=100)
        self.progress.pack(fill=BOTH, pady=(0, 6))
        self.status_label = ttk.Label(log_frame, text="Listo.")
        self.status_label.pack(anchor="w")

        text_container = Frame(log_frame)
        text_container.pack(fill=BOTH, expand=True)
        log_scroll = Scrollbar(text_container)
        log_scroll.pack(side=RIGHT, fill="y")
        self.log_text = Text(
            text_container,
            height=10,
            wrap="word",
            yscrollcommand=log_scroll.set,
            font=("Consolas", 9),
        )
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        log_scroll.config(command=self.log_text.yview)

        actions = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        actions.pack(fill=BOTH, side="bottom", before=body)

        self.pro_btn = ttk.Button(
            actions, text="INSTALACIÓN PROFESIONAL", command=self.start_professional
        )
        self.pro_btn.pack(side=LEFT, padx=(0, 8))

        self.download_only_btn = ttk.Button(
            actions, text="Solo descargar", command=lambda: self.start_work(install=False)
        )
        self.download_only_btn.pack(side=LEFT, padx=(0, 8))

        self.install_btn = ttk.Button(
            actions,
            text="Descargar e instalar",
            command=lambda: self.start_work(install=True),
        )
        self.install_btn.pack(side=LEFT, padx=(0, 8))

        self.cancel_btn = ttk.Button(
            actions, text="Cancelar", command=self.cancel_work, state="disabled"
        )
        self.cancel_btn.pack(side=LEFT)

        ttk.Button(actions, text="Abrir logs", command=self.open_logs).pack(side=RIGHT)
        ttk.Button(actions, text="Abrir downloads", command=self.open_downloads).pack(
            side=RIGHT, padx=(0, 8)
        )
        ttk.Button(actions, text="Salir", command=self.root.destroy).pack(
            side=RIGHT, padx=(0, 8)
        )

    def append_log(self, message: str) -> None:
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        log_message(message)

    def set_status(self, message: str) -> None:
        self.status_label.config(text=message)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.download_only_btn.config(state=state)
        self.install_btn.config(state=state)
        self.pro_btn.config(state=state)
        self.cancel_btn.config(state="normal" if busy else "disabled")
        self.running = busy
        if not busy:
            self.cancel_event.clear()

    def cancel_work(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.append_log("Cancelando tras el paso actual...")

    def selected_programs(self) -> list[Program]:
        return [p for p in self.programs if self.vars[p.id].get()]

    def apply_preset(self, preset: Preset) -> None:
        self.select_none()
        program_map = {p.id: p for p in self.programs}
        applied = 0

        for pid in preset.program_ids:
            program = program_map.get(pid)
            if not program:
                self.append_log(f"AVISO: '{pid}' del perfil '{preset.name}' no existe.")
                continue
            if preset.smart_gpu and program.gpu_filter:
                continue
            self.vars[pid].set(True)
            applied += 1

        if preset.smart_gpu:
            for program in self.programs:
                if not program.gpu_filter:
                    continue
                if gpu_matches_filter(program.gpu_filter, self.gpu_names):
                    self.vars[program.id].set(True)
                    applied += 1
            self.append_log(
                f"Perfil '{preset.name}': {applied} elementos "
                f"(GPU: {gpu_vendor_label(self.gpu_names)})."
            )
            return

        self.append_log(f"Perfil '{preset.name}': {applied} elementos marcados.")

    def select_all(self) -> None:
        for var in self.vars.values():
            var.set(True)

    def select_none(self) -> None:
        for var in self.vars.values():
            var.set(False)

    def refresh_system(self) -> None:
        self.system_info = detect_system_info()
        self.gpu_names = self.system_info.gpus
        self.append_log("--- Reescaneo del sistema ---")
        self._log_startup()
        messagebox.showinfo(
            "Sistema",
            f"{self.system_info.os_display}\n"
            f"{self.system_info.cpu}\nRAM {self.system_info.ram_gb} GB\n"
            f"GPU: {gpu_vendor_label(self.gpu_names)}\n"
            f"Disco: {self.system_info.disk_summary}\n"
            f"Internet: {'sí' if self.system_info.internet else 'no'}",
        )

    def request_admin(self) -> None:
        if messagebox.askyesno(
            "Administrador",
            "Se reiniciará PretelToolkit como administrador.\n¿Continuar?",
        ):
            relaunch_as_admin()
            self.root.destroy()

    def open_downloads(self) -> None:
        os.startfile(self.download_dir)

    def open_logs(self) -> None:
        os.startfile(LOGS_DIR)

    def open_config_info(self) -> None:
        info = Toplevel(self.root)
        info.title("Editar lista")
        info.geometry("640x220")
        ttk.Label(info, text="Edita programas y perfiles en:", padding=12).pack(anchor="w")
        ttk.Label(info, text=str(CONFIG_PATH), font=("Consolas", 10)).pack(
            anchor="w", padx=12
        )
        ttk.Button(
            info,
            text="Abrir carpeta config",
            command=lambda: os.startfile(CONFIG_PATH.parent),
        ).pack(padx=12, pady=8, anchor="w")

    def start_professional(self) -> None:
        if self.running:
            return

        if not self.selected_programs():
            oficina = next(
                (p for p in self.presets if p.key in ("oficina", "pc_oficina", "basico")),
                None,
            )
            if oficina is None:
                self.select_none()
                for program in self.programs:
                    if program.recommended or (
                        program.gpu_filter
                        and gpu_matches_filter(program.gpu_filter, self.gpu_names)
                    ):
                        self.vars[program.id].set(True)
            else:
                self.apply_preset(oficina)

        checks: list[str] = []
        if not (self.system_info.internet or check_internet()):
            messagebox.showerror(
                "Sin Internet",
                "No hay conexión a Internet. La instalación profesional necesita red.",
            )
            return
        checks.append("Internet OK")

        if not is_admin():
            if not messagebox.askyesno(
                "Admin recomendado",
                "Para instalación profesional conviene ser administrador.\n¿Continuar igualmente?",
            ):
                return
        else:
            checks.append("Admin OK")

        selected = self.selected_programs()
        if not selected:
            messagebox.showwarning("Vacío", "No hay programas seleccionados.")
            return

        msg = (
            "INSTALACIÓN PROFESIONAL\n\n· "
            f"{self.system_info.os_display}\n· "
            f"{self.system_info.arch}\n· GPU: "
            f"{gpu_vendor_label(self.gpu_names)}\n· Programas: "
            f"{len(selected)}\n· Luego abrirá Windows Update\n· Creará informe en logs\\\n\n¿Continuar?"
        )
        if not messagebox.askyesno("Instalación profesional", msg):
            return

        self.append_log("=== INSTALACIÓN PROFESIONAL ===")
        for c in checks:
            self.append_log(f"Check: {c}")

        self.cancel_event.clear()
        self.set_busy(True)
        threading.Thread(
            target=self._worker, args=(selected, True, True), daemon=True
        ).start()

    def start_work(self, install: bool) -> None:
        if self.running:
            return
        selected = self.selected_programs()
        if not selected:
            messagebox.showwarning("Selección vacía", "Marca al menos un programa o driver.")
            return

        if install and any(p.requires_admin for p in selected) and not is_admin():
            if not messagebox.askyesno(
                "Permisos",
                "Algunos elementos requieren administrador.\n¿Continuar?",
            ):
                return

        self.cancel_event.clear()
        self.set_busy(True)
        threading.Thread(
            target=self._worker, args=(selected, install, False), daemon=True
        ).start()

    def _process_one(self, program: Program, install: bool) -> None:
        destination = self.download_dir / program.filename

        if (
            install
            and self.prefer_winget.get()
            and program.winget_id
            and not program.portable
            and winget_available()
        ):
            self.root.after(0, lambda: self.set_status(f"winget: {program.name}"))
            code = install_via_winget(program.winget_id)
            if code == 0:
                record_result(program.name, True, "instalado vía winget (última versión)")
                self.root.after(0, lambda: self.append_log(f"[OK] {program.name} — winget"))
                return
            self.root.after(
                0,
                lambda: self.append_log(f"winget falló ({code}), intento descarga directa..."),
            )

        if program.url_type == "manual_download":
            webbrowser.open(program.url)
            raise RuntimeError("Descarga manual: abre la web y guarda en downloads.")

        url = resolve_download_url(program)

        def progress_cb(percent: int, done: int, total_size: int) -> None:
            p = program
            if percent >= 0:
                self.root.after(0, lambda v=percent: self.progress.config(value=v))
                if total_size:
                    mb_done = done / 1048576
                    mb_total = total_size / 1048576
                    self.root.after(
                        0,
                        lambda: self.set_status(
                            f"Descargando {p.name}: {percent}% ({mb_done:.1f}/{mb_total:.1f} MB)"
                        ),
                    )

        if destination.exists() and destination.stat().st_size > 1024:
            self.root.after(0, lambda: self.append_log(f"Ya descargado: {destination.name}"))
        else:
            download_file(url, destination, progress_cb, self.cancel_event)
            self.root.after(0, lambda: self.append_log(f"Descargado: {destination.name}"))

        if self.cancel_event.is_set():
            raise RuntimeError("Cancelado")

        if not install:
            record_result(program.name, True, "descargado")
            return

        if program.portable:
            tools_dir = self.download_dir / "herramientas"
            tools_dir.mkdir(exist_ok=True)
            target = tools_dir / program.filename
            if destination.resolve() != target.resolve():
                shutil.copy2(destination, target)
            record_result(program.name, True, f"portable → {target.name}")
            self.root.after(0, lambda: self.append_log(f"[OK] {program.name} — portable"))
            return

        self.root.after(0, lambda: self.set_status(f"Instalando: {program.name}"))
        code = run_installer(destination, program.install_args, program.requires_admin)
        if code == 0:
            record_result(program.name, True, "instalado")
            self.root.after(0, lambda: self.append_log(f"[OK] {program.name} — instalado"))
            return
        record_result(program.name, False, f"código {code}")
        self.root.after(
            0, lambda: self.append_log(f"[ERROR] {program.name} — código {code}")
        )

    def _worker(self, selected: list[Program], install: bool, professional: bool) -> None:
        global _session_results
        _session_results = []
        total = len(selected)

        for index, program in enumerate(selected, start=1):
            if self.cancel_event.is_set():
                self.root.after(0, lambda: self.append_log("Proceso cancelado."))
                break
            self.root.after(
                0, lambda p=program, i=index: self.set_status(f"[{i}/{total}] {p.name}")
            )
            self.root.after(0, lambda p=program: self.append_log(f"--- {p.name} ---"))
            try:
                self._process_one(program, install)
            except Exception as exc:
                record_result(program.name, False, str(exc))
                self.root.after(
                    0, lambda p=program, e=exc: self.append_log(f"[ERROR] {p.name}: {e}")
                )
            self.root.after(0, lambda: self.progress.config(value=0))

        wu_msg = ""
        if professional and not self.cancel_event.is_set():
            self.root.after(0, lambda: self.set_status("Windows Update..."))
            self.root.after(0, lambda: self.append_log("--- Windows Update ---"))
            wu_msg = trigger_windows_update()
            self.root.after(0, lambda m=wu_msg: self.append_log(m))

        report = write_final_report()
        ok_n = sum(1 for r in _session_results if r.ok)
        fail_n = sum(1 for r in _session_results if not r.ok)
        summary = f"Finalizado: {ok_n} OK, {fail_n} errores. Informe: {report.name}"

        self.root.after(0, lambda: self.append_log(""))
        self.root.after(0, lambda: self.append_log("=== RESUMEN ==="))
        for r in _session_results:
            mark = "[OK]" if r.ok else "[ERROR]"
            self.root.after(
                0,
                lambda m=mark, n=r.name, d=r.detail: self.append_log(
                    f"{m} {n}" + (f" — {d}" if d else "")
                ),
            )
        self.root.after(0, lambda: self.append_log(summary))
        self.root.after(0, lambda: self.set_status(summary))
        self.root.after(0, lambda: self.set_busy(False))
        self.root.after(
            0,
            lambda: messagebox.showinfo(
                "Finalizado", f"{summary}\n\nCarpeta logs:\n{LOGS_DIR}"
            ),
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ensure_dirs()
    try:
        app = SetupPCApp()
        app.run()
    except Exception as exc:
        messagebox.showerror("Error", str(exc))
        raise


if __name__ == "__main__":
    main()


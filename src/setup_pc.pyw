"""
PretelToolkit - Herramienta de técnico post-formateo para Windows
"""

from __future__ import annotations

import base64
import ctypes
import functools
import hashlib
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
import time
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes
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
APP_VERSION = "3.1.0"

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PretelToolkit/3.0"
# SourceForge sirve una página HTML a los navegadores y el instalador real a curl/wget.
CURL_USER_AGENT = "curl/8.4.0"

# Códigos de salida que cuentan como instalación correcta.
INSTALL_OK_CODES = {
    0: "instalado",
    1638: "ya había una versión igual o más reciente instalada",
    1641: "instalado (el instalador ha iniciado un reinicio)",
    3010: "instalado (requiere reiniciar Windows)",
}

CACHE_MAX_AGE_DAYS = 14
INSTALLER_TIMEOUT = 3600


# --------------------------------------------------------------------------- #
# Aspecto: "telemetría táctica" (modo oscuro, un único acento rojo, monoespaciada,
# esquinas rectas y líneas de 1 px). Todo lo visual vive aquí y en _build_*.
# --------------------------------------------------------------------------- #

BG = "#0A0A0A"      # CRT apagado
PANEL = "#121212"
FG = "#EAEAEA"      # fósforo blanco
DIM = "#8A8A8A"
LINE = "#3A3A3A"
RED = "#E61919"     # único acento
GREEN = "#4AF626"   # solo para el indicador ONLINE
MONO = "Consolas"
HEAVY = "Arial Black"


def apply_theme(root: Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        ".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=LINE,
        lightcolor=BG, darkcolor=BG, troughcolor=PANEL, focuscolor=BG, font=(MONO, 9),
    )
    style.configure("TLabelframe", background=BG, bordercolor=LINE, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=FG, font=(MONO, 9, "bold"))
    style.configure("Title.TLabel", font=(HEAVY, 26), foreground=FG)
    style.configure("Meta.TLabel", font=(MONO, 8), foreground=DIM)
    style.configure("Head.TLabel", font=(MONO, 10, "bold"), foreground=FG)
    style.configure("Ok.TLabel", font=(MONO, 9, "bold"), foreground=GREEN)
    style.configure("Err.TLabel", font=(MONO, 9, "bold"), foreground=RED)

    style.configure(
        "TButton", background=PANEL, foreground=FG, bordercolor=FG, lightcolor=PANEL,
        darkcolor=PANEL, borderwidth=1, relief="flat", focuscolor=PANEL, padding=(12, 6),
        font=(MONO, 9, "bold"),
    )
    style.map(
        "TButton",
        background=[("disabled", BG), ("pressed", RED), ("active", FG)],
        foreground=[("disabled", "#555555"), ("active", BG)],
        bordercolor=[("disabled", "#2A2A2A")],
        lightcolor=[("active", FG)], darkcolor=[("active", FG)],
    )
    style.configure(
        "Primary.TButton", background=RED, foreground="#FFFFFF", bordercolor=RED,
        lightcolor=RED, darkcolor=RED,
    )
    style.map(
        "Primary.TButton",
        background=[("disabled", "#3A1010"), ("pressed", "#FFFFFF"), ("active", FG)],
        foreground=[("disabled", "#777777"), ("active", RED), ("pressed", RED)],
        bordercolor=[("disabled", "#3A1010")],
        lightcolor=[("active", FG)], darkcolor=[("active", FG)],
    )

    style.configure(
        "TCheckbutton", background=BG, foreground=FG, font=(MONO, 10),
        indicatorbackground=PANEL, indicatorforeground="#FFFFFF",
        upperbordercolor=FG, lowerbordercolor=FG,
    )
    style.map(
        "TCheckbutton",
        background=[("active", BG)], foreground=[("active", FG)],
        indicatorbackground=[("selected", RED), ("pressed", FG)],
    )
    style.configure(
        "Horizontal.TProgressbar", troughcolor=PANEL, background=RED, bordercolor=LINE,
        lightcolor=RED, darkcolor=RED, thickness=8,
    )
    style.configure(
        "Vertical.TScrollbar", background="#2A2A2A", troughcolor=PANEL, bordercolor=BG,
        arrowcolor=FG, lightcolor="#2A2A2A", darkcolor="#2A2A2A", relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", FG)])

    # Barra de título oscura (Windows 10 20H1+); si no existe, se ignora.
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
    except Exception:
        pass


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    # En desarrollo el script vive en src/; la carpeta del programa es la de arriba.
    return here.parent if here.name == "src" else here


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
    user_agent: str | None = None
    referer: str | None = None
    sha256: str | None = None
    unsupported_gpu_regex: str | None = None
    unsupported_url: str | None = None


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
_config_warnings: list[str] = []
_log_lock = threading.Lock()


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


def _append_setup_log(message: str) -> None:
    """setup.log acumula todas las sesiones: lleva fecha completa y se rota a 1 MB."""
    path = LOGS_DIR / "setup.log"
    try:
        if path.exists() and path.stat().st_size > 1_000_000:
            path.replace(LOGS_DIR / "setup.old.log")
    except OSError:
        pass
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def log_message(message: str) -> None:
    with _log_lock:
        ensure_dirs()
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        if _session_log is None:
            start_session_log()
        assert _session_log is not None
        with _session_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _append_setup_log(message)


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
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relanza el programa con UAC. Devuelve False si el usuario cancela o falla."""
    if getattr(sys, "frozen", False):
        args = sys.argv[1:]
        # Un .exe de PyInstaller relanzado desde sí mismo hereda la carpeta temporal
        # (_MEI...) del padre, que se borra al cerrarse este: hay que reiniciar el entorno
        # para que la nueva instancia extraiga la suya.
        for key in list(os.environ):
            if key.startswith(("_PYI", "_MEI")):
                del os.environ[key]
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        args = sys.argv
    params = " ".join(f'"{arg}"' for arg in args)
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, str(BASE_DIR), 1
    )
    return result > 32


def _run_hidden(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=timeout,
    )


def _run_powershell(script: str, timeout: int = 45, env: dict | None = None) -> str:
    """Ejecuta PowerShell con salida UTF-8 (evita problemas de codificación OEM)."""
    full = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + script
    encoded = base64.b64encode(full.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=timeout,
        env=env,
    )
    return result.stdout.decode("utf-8-sig", errors="replace")


def check_internet(timeout: float = 3.0) -> bool:
    """Prueba varios puertos: algunas redes bloquean el 53 pero dejan pasar HTTPS/HTTP."""
    targets = [
        ("1.1.1.1", 443),
        ("8.8.8.8", 53),
        ("1.1.1.1", 53),
        ("www.msftconnecttest.com", 80),
    ]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------- #
# Detección del equipo
# --------------------------------------------------------------------------- #

_PS_DETECT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$os  = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
$gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
    [pscustomobject]@{ name = [string]$_.Name; pnp = [string]$_.PNPDeviceID } })
$disks = @(Get-PhysicalDisk | Where-Object { $_.BusType -ne 'USB' } | ForEach-Object {
    [pscustomobject]@{ media = [string]$_.MediaType; bus = [string]$_.BusType } })
[pscustomobject]@{
    os    = if ($os) { '{0} (Build {1})' -f $os.Caption.Trim(), $os.BuildNumber } else { '' }
    cpu   = if ($cpu) { ([string]$cpu.Name).Trim() } else { '' }
    ram   = if ($cs) { [double]$cs.TotalPhysicalMemory } else { 0 }
    gpus  = $gpus
    disks = $disks
} | ConvertTo-Json -Compress -Depth 4
"""

_PCI_VENDORS = {
    "10DE": "NVIDIA",
    "1002": "AMD Radeon",
    "1022": "AMD",
    "8086": "Intel",
}


def _gpu_label(name: str, pnp: str) -> str:
    """En un PC recién formateado Windows llama a la GPU 'Microsoft Basic Display
    Adapter'. El identificador PCI (VEN_xxxx) delata el fabricante real."""
    name = (name or "").strip()
    match = re.search(r"VEN_([0-9A-F]{4})", pnp or "", re.IGNORECASE)
    vendor = _PCI_VENDORS.get(match.group(1).upper()) if match else None
    lowered = name.lower()
    if vendor and not any(v in lowered for v in ("nvidia", "amd", "radeon", "intel")):
        return f"{vendor} (sin driver: {name or 'adaptador básico'})"
    return name


def _disk_summary_from(disks: list[dict]) -> str:
    kinds: set[str] = set()
    for disk in disks:
        media = str(disk.get("media", "")).upper()
        bus = str(disk.get("bus", "")).upper()
        if media == "SSD" or bus == "NVME":
            kinds.add("SSD")
        else:
            kinds.add("HDD")
    order = ["SSD", "HDD"]
    return " · ".join(k for k in order if k in kinds)


def _detect_via_powershell() -> dict | None:
    """Una sola llamada a PowerShell para todo (antes eran 5-6 procesos, con wmic
    que ya no existe en Windows 11 24H2)."""
    try:
        out = _run_powershell(_PS_DETECT, timeout=60).strip()
        start = out.find("{")
        if start < 0:
            return None
        data = json.loads(out[start:])
    except Exception:
        return None
    for key in ("gpus", "disks"):
        value = data.get(key)
        if isinstance(value, dict):
            data[key] = [value]
        elif not isinstance(value, list):
            data[key] = []
    return data


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
    ver = platform.version()
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
        build = int(ver.split(".")[2]) if ver.count(".") >= 2 else 0
        name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{name} (Build {build or '?'})"
    except Exception:
        return f"Windows {ver}"


def _windows_display_from_platform() -> str:
    ver = platform.version()
    try:
        build = int(ver.split(".")[2]) if ver.count(".") >= 2 else 0
        name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{name} (Build {build or '?'})"
    except Exception:
        return f"Windows {ver}"


def detect_system_info() -> SystemInfo:
    net: dict[str, bool] = {}

    def _net() -> None:
        net["ok"] = check_internet()

    net_thread = threading.Thread(target=_net, daemon=True)
    net_thread.start()

    info = SystemInfo(
        os_name=platform.system(),
        arch=platform.machine() or ("AMD64" if sys.maxsize > 2**32 else "x86"),
        admin=is_admin(),
    )

    data = _detect_via_powershell()
    if data:
        info.os_display = str(data.get("os") or "")
        info.cpu = str(data.get("cpu") or "")
        try:
            ram = float(data.get("ram") or 0)
            if ram > 0:
                info.ram_gb = round(ram / (1024**3), 1)
        except (TypeError, ValueError):
            pass
        info.gpus = [
            label
            for label in (
                _gpu_label(g.get("name", ""), g.get("pnp", ""))
                for g in data["gpus"]
                if isinstance(g, dict)
            )
            if label
        ]
        info.disk_summary = _disk_summary_from(
            [d for d in data["disks"] if isinstance(d, dict)]
        )

    # Alternativas por si PowerShell/CIM no respondió (equipos antiguos o restringidos).
    if not info.os_display:
        info.os_display = (
            _windows_display_from_platform() if data else detect_windows_display()
        )
    if not info.cpu:
        try:
            result = _run_hidden(["wmic", "cpu", "get", "name"])
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and line.lower() != "name":
                    info.cpu = line
                    break
        except Exception:
            pass
        info.cpu = info.cpu or platform.processor() or "Desconocido"
    if not info.ram_gb:
        try:
            result = _run_hidden(["wmic", "computersystem", "get", "totalphysicalmemory"])
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    info.ram_gb = round(int(line) / (1024**3), 1)
                    break
        except Exception:
            pass
    if not info.gpus:
        info.gpus = detect_gpu_names()
    if not info.disk_summary:
        info.disk_summary = detect_disks()

    net_thread.join(timeout=20)
    info.internet = net.get("ok", False)
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


def gpu_is_legacy(program: Program, gpu_names: list[str]) -> bool:
    """True si TODAS las GPU del fabricante son demasiado antiguas para el instalador
    fijo que trae el programa (regex 'unsupported_gpu_regex' de software.json)."""
    if not program.gpu_filter or not program.unsupported_gpu_regex:
        return False
    matching = [g for g in gpu_names if gpu_matches_filter(program.gpu_filter, [g])]
    if not matching:
        return False
    try:
        pattern = re.compile(program.unsupported_gpu_regex, re.IGNORECASE)
    except re.error:
        return False
    return all(pattern.search(g) for g in matching)


def gpu_status(program: Program, gpu_names: list[str]) -> str:
    """'any' (sin filtro), 'ok', 'other' (otra marca) o 'legacy' (GPU demasiado
    antigua para el instalador fijo). Si el programa busca el driver en la web del
    fabricante (nvidia_lookup), una GPU antigua no es un problema."""
    if not program.gpu_filter:
        return "any"
    if not any(gpu_matches_filter(program.gpu_filter, [g]) for g in gpu_names):
        return "other"
    if program.url_type != "nvidia_lookup" and gpu_is_legacy(program, gpu_names):
        return "legacy"
    return "ok"


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #


def load_config() -> tuple[list[Program], list[Preset], Path]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No se encuentra la configuración: {CONFIG_PATH}")

    _config_warnings.clear()
    try:
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "El archivo software.json tiene un error de formato "
            f"(línea {exc.lineno}, columna {exc.colno}): {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("El archivo software.json debe contener un objeto JSON.")

    download_dir = BASE_DIR / data.get("download_folder", "downloads")
    download_dir.mkdir(parents=True, exist_ok=True)

    programs: list[Program] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(data.get("programs", []), start=1):
        if not isinstance(item, dict):
            _config_warnings.append(f"programa #{index} ignorado: no es un objeto.")
            continue
        missing = [k for k in ("id", "name", "url", "filename") if not item.get(k)]
        if missing:
            _config_warnings.append(
                f"programa #{index} ({item.get('id', '?')}) ignorado: "
                f"faltan {', '.join(missing)}."
            )
            continue
        if item["id"] in seen_ids:
            _config_warnings.append(f"programa '{item['id']}' repetido: se ignora el duplicado.")
            continue
        seen_ids.add(item["id"])
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
                user_agent=item.get("user_agent"),
                referer=item.get("referer"),
                sha256=item.get("sha256"),
                unsupported_gpu_regex=item.get("unsupported_gpu_regex"),
                unsupported_url=item.get("unsupported_url"),
            )
        )

    presets: list[Preset] = []
    for key, preset in data.get("presets", {}).items():
        if not isinstance(preset, dict):
            _config_warnings.append(f"perfil '{key}' ignorado: no es un objeto.")
            continue
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


@functools.lru_cache(maxsize=1)
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
        cmd, creationflags=subprocess.CREATE_NO_WINDOW, timeout=INSTALLER_TIMEOUT
    )
    # 0x8A15002B = ya instalado / sin actualización; 0x8A150061 = paquete ya instalado
    if (completed.returncode & 0xFFFFFFFF) in (2316632107, 2316632161):
        log_message("winget: ya estaba instalado y actualizado.")
        return 0
    return completed.returncode


def resolve_adobe_reader_url(page_url: str) -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(page_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
        html = response.read().decode("utf-8", errors="ignore")
    match = re.search(r"https://[^\"']+Reader[^\"']+\.exe", html, re.IGNORECASE)
    if match:
        return match.group(0)
    raise RuntimeError(
        "No se pudo encontrar el enlace de Adobe Reader (la web de Adobe ya no lo "
        "publica en el HTML). Márcalo como 'manual_download' en software.json."
    )


def _curl_path() -> str | None:
    curl = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "curl.exe")
    return curl if os.path.exists(curl) else None


def _fetch_bytes(url: str, timeout: int = 25) -> bytes:
    """GET sencillo; si Python no reconoce el certificado (Windows recién instalado)
    reintenta con el curl.exe de Windows."""
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with urllib.request.urlopen(
            req, context=ssl.create_default_context(), timeout=timeout
        ) as response:
            return response.read()
    except (urllib.error.URLError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        curl = _curl_path()
        if not isinstance(reason, ssl.SSLCertVerificationError) or not curl:
            raise
        result = subprocess.run(
            [curl, "-L", "--fail", "-s", "-S", "-A", DEFAULT_USER_AGENT, url],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl.exe falló (código {result.returncode})")
        return result.stdout


NVIDIA_PRODUCTS_API = "https://www.nvidia.com/Download/API/lookupValueSearch.aspx"
NVIDIA_DRIVER_API = (
    "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/"
    "AjaxDriverService.php"
)


def _nvidia_values(type_id: int, parent_id: int | None = None) -> list[tuple[str, str]]:
    import xml.etree.ElementTree as ET

    url = f"{NVIDIA_PRODUCTS_API}?TypeID={type_id}"
    if parent_id is not None:
        url += f"&ParentID={parent_id}"
    root = ET.fromstring(_fetch_bytes(url))
    return [
        (v.findtext("Name") or "", v.findtext("Value") or "")
        for v in root.iter("LookupValue")
    ]


def _norm_gpu(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("nvidia", ""))


def _find_nvidia_product(gpu_name: str) -> tuple[str, str] | None:
    """Localiza (id de serie, id de producto) de una GeForce en la base de NVIDIA."""
    wanted = _norm_gpu(gpu_name)
    number = re.search(r"(\d{3,4})", gpu_name)
    family = ""
    if number:
        digits = number.group(1)
        family = digits[:2] if len(digits) == 4 else digits[0] + "00"
    series = _nvidia_values(2, 1)
    # Primero las series de la misma familia (p. ej. "GeForce 900 Series" para una 970).
    series.sort(key=lambda s: 0 if family and re.search(rf"\b{family}\b", s[0]) else 1)
    for _series_name, series_id in series:
        best: tuple[str, str] | None = None
        for product_name, product_id in _nvidia_values(3, int(series_id)):
            norm = _norm_gpu(product_name)
            if wanted.startswith(norm) and (best is None or len(norm) > len(_norm_gpu(best[0]))):
                best = (product_name, product_id)
        if best:
            return series_id, best[1]
    return None


def resolve_nvidia_driver(gpu_names: list[str]) -> tuple[str, str]:
    """Pregunta a NVIDIA por el driver Game Ready más reciente compatible con la GPU.
    Devuelve (url, version). Para tarjetas antiguas devuelve su último driver soportado."""
    candidates = [
        g
        for g in gpu_names
        if "geforce" in g.lower() and "sin driver" not in g.lower()
    ]
    if not candidates:
        raise RuntimeError("no se conoce el modelo exacto de la GPU NVIDIA")
    last_error: Exception | None = None
    for gpu in candidates:
        try:
            product = _find_nvidia_product(gpu)
            if not product:
                raise RuntimeError(f"'{gpu}' no aparece en la base de NVIDIA")
            series_id, product_id = product
            query = (
                f"?func=DriverManualLookup&psid={series_id}&pfid={product_id}&osID=57"
                "&languageCode=1033&beta=0&isWHQL=1&dltype=-1&dch=1&upCRD=0&qnf=0"
                "&sort1=1&numberOfResults=10"
            )
            data = json.loads(_fetch_bytes(NVIDIA_DRIVER_API + query))
            found: list[tuple[tuple[int, ...], str, str]] = []
            for entry in data.get("IDS", []):
                info = entry.get("downloadInfo", {})
                url, version = info.get("DownloadURL"), info.get("Version")
                if url and version and url.lower().endswith(".exe"):
                    key = tuple(int(p) for p in re.findall(r"\d+", version))
                    found.append((key, url, version))
            if not found:
                raise RuntimeError(f"NVIDIA no ofrece driver para '{gpu}'")
            _key, url, version = max(found)
            return url, version
        except Exception as exc:  # pruebo con la siguiente GPU
            last_error = exc
    raise RuntimeError(str(last_error))


def resolve_download_url(program: Program, gpu_names: list[str] | None = None) -> str:
    if program.url_type == "nvidia_lookup":
        try:
            url, version = resolve_nvidia_driver(gpu_names or [])
            log_message(f"NVIDIA: driver más reciente compatible con tu GPU: {version}")
            return url
        except Exception as exc:
            log_message(
                f"NVIDIA: no se pudo consultar la web de NVIDIA ({exc}); "
                "se usa el driver incluido en software.json."
            )
            return program.url
    if program.url_type == "adobe_reader":
        return resolve_adobe_reader_url(program.url)
    if program.url_type == "malwarebytes":
        return "https://data-cdn.mbamupdates.com/web/mb4-setup-consumer/offline/MBSetup.exe"
    if program.url_type == "manual_download":
        raise RuntimeError(f"{program.name}: descarga manual requerida.")
    return program.url


# --------------------------------------------------------------------------- #
# Descargas: archivo temporal, validación, caché con índice y verificación
# --------------------------------------------------------------------------- #


def _looks_like_installer(path: Path, suffix: str | None = None) -> bool:
    suffix = (suffix or path.suffix).lower()
    try:
        with path.open("rb") as f:
            head = f.read(8)
    except OSError:
        return False
    if suffix == ".exe":
        return head.startswith(b"MZ")
    if suffix == ".msi":
        return head.startswith(b"\xd0\xcf\x11\xe0")
    return True


def _cache_index_path(directory: Path) -> Path:
    return directory / ".cache.json"


def _load_cache_index(directory: Path) -> dict:
    try:
        with _cache_index_path(directory).open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache_index(directory: Path, index: dict) -> None:
    try:
        with _cache_index_path(directory).open("w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)
    except OSError:
        pass


def _cache_record(destination: Path, url: str) -> None:
    directory = destination.parent
    index = _load_cache_index(directory)
    try:
        size = destination.stat().st_size
    except OSError:
        return
    index[destination.name] = {"url": url, "size": size}
    _save_cache_index(directory, index)


def _cache_forget(destination: Path) -> None:
    directory = destination.parent
    index = _load_cache_index(directory)
    if index.pop(destination.name, None) is not None:
        _save_cache_index(directory, index)


def cached_download_is_usable(destination: Path, url: str) -> bool:
    """Una descarga previa solo se reutiliza si se hizo desde la misma URL, tiene el
    mismo tamaño que cuando se completó, parece un instalador y no es muy antigua."""
    entry = _load_cache_index(destination.parent).get(destination.name)
    if not isinstance(entry, dict) or entry.get("url") != url:
        return False
    try:
        stat = destination.stat()
    except OSError:
        return False
    if stat.st_size <= 1024 or stat.st_size != entry.get("size"):
        return False
    if time.time() - stat.st_mtime > CACHE_MAX_AGE_DAYS * 86400:
        return False
    return _looks_like_installer(destination)


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _authenticode_status(path: Path) -> tuple[str, str]:
    env = dict(os.environ, PT_FILE=str(path))
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:PT_FILE; "
        "$subj = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' }; "
        "'{0}|{1}' -f $s.Status, $subj"
    )
    try:
        out = _run_powershell(script, timeout=60, env=env).strip().splitlines()
        if out:
            status, _, subject = out[-1].partition("|")
            return status.strip(), subject.strip()
    except Exception:
        pass
    return "Unknown", ""


def verify_download(path: Path, expected_sha256: str | None) -> None:
    """Comprueba SHA-256 (si el JSON lo trae) y la firma digital (Authenticode)."""
    if expected_sha256:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest().lower() != expected_sha256.strip().lower():
            _remove_quietly(path)
            _cache_forget(path)
            raise RuntimeError(
                "La descarga no coincide con el SHA-256 esperado de software.json "
                "(archivo corrupto o modificado). Se ha borrado."
            )
        log_message(f"SHA-256 verificado: {path.name}")
    status, subject = _authenticode_status(path)
    if status == "Valid":
        log_message(f"Firma digital válida: {subject or path.name}")
    elif status == "HashMismatch":
        _remove_quietly(path)
        _cache_forget(path)
        raise RuntimeError(
            "La firma digital del instalador no es válida (el archivo ha sido "
            "modificado). Se ha borrado."
        )
    else:
        log_message(f"AVISO: {path.name} sin firma digital verificable ({status}).")


def _download_to(
    url: str,
    part: Path,
    progress_cb,
    cancel_event: threading.Event,
    user_agent: str,
    referer: str | None,
) -> None:
    headers = {"User-Agent": user_agent}
    if referer:
        headers["Referer"] = referer
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=120) as response:
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            with part.open("wb") as out:
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
            if total and done != total:
                raise RuntimeError(
                    f"Descarga incompleta ({done} de {total} bytes). Vuelve a intentarlo."
                )
    except (urllib.error.URLError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        if not isinstance(reason, ssl.SSLCertVerificationError):
            raise
        curl = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "curl.exe")
        if not os.path.exists(curl):
            raise
        log_message("Certificado no reconocido por Python; reintentando con curl.exe de Windows...")
        cmd = [curl, "-L", "--fail", "-s", "-S", "-A", user_agent]
        if referer:
            cmd += ["-e", referer]
        cmd += ["-o", str(part), url]
        proc = subprocess.Popen(
            cmd,
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
                size = part.stat().st_size if part.exists() else 0
                progress_cb(-1, size, 0)
        if proc.returncode != 0:
            err = proc.stderr.read().decode("utf-8", "ignore").strip()
            raise RuntimeError(f"curl.exe falló (código {proc.returncode}): {err}")


def download_file(
    url: str,
    destination: Path,
    progress_cb,
    cancel_event: threading.Event,
    user_agent: str | None = None,
    referer: str | None = None,
    sha256: str | None = None,
) -> None:
    if not user_agent:
        user_agent = CURL_USER_AGENT if "sourceforge.net" in url else DEFAULT_USER_AGENT
    # Se descarga a un .part y solo se renombra cuando está completo y validado: así
    # una descarga cancelada o cortada nunca se confunde con un instalador válido.
    part = destination.with_name(destination.name + ".part")
    try:
        _download_to(url, part, progress_cb, cancel_event, user_agent, referer)
        if not _looks_like_installer(part, destination.suffix):
            raise RuntimeError(
                "El enlace no ha devuelto un instalador (parece una página web). "
                "Revisa la 'url' de este programa en software.json."
            )
        os.replace(part, destination)
    except BaseException:
        _remove_quietly(part)
        raise
    _cache_record(destination, url)
    verify_download(destination, sha256)


# --------------------------------------------------------------------------- #
# Ejecución de instaladores
# --------------------------------------------------------------------------- #


def build_install_command(installer: Path, args: list[str]) -> list[str]:
    if installer.suffix.lower() == ".msi":
        return ["msiexec", "/i", str(installer), *args]
    return [str(installer), *args]


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_NO_UI = 0x00000400  # sin cuadros de error de Windows (el UAC sí se muestra)
ERROR_CANCELLED = 1223
WAIT_TIMEOUT = 0x00000102


def _shell_execute_wait(
    exe: str,
    params: str,
    directory: str | None,
    verb: str = "runas",
    timeout: int = INSTALLER_TIMEOUT,
) -> int:
    """Lanza un proceso (con UAC si verb='runas'), ESPERA a que termine y devuelve su
    código de salida. ShellExecuteW no espera: antes se daba por instalado un
    programa que solo acababa de empezar."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    info = _SHELLEXECUTEINFOW()
    for attempt in range(3):
        info = _SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
        info.lpVerb = verb
        info.lpFile = exe
        info.lpParameters = params or None
        info.lpDirectory = directory
        info.nShow = 1
        if shell32.ShellExecuteExW(ctypes.byref(info)):
            break
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise RuntimeError(
                "Se canceló la ventana de permisos (UAC): no se concedieron "
                "permisos de administrador."
            )
        # 2/3/32: archivo recién descargado todavía bloqueado (antivirus/SmartScreen).
        if error in (2, 3, 32) and attempt < 2:
            time.sleep(2)
            continue
        raise RuntimeError(
            f"No se pudo lanzar el instalador con permisos de administrador (error {error})."
        )

    handle = info.hProcess
    if not handle:
        raise RuntimeError("Windows no devolvió el proceso del instalador; no se puede confirmar.")
    try:
        if kernel32.WaitForSingleObject(handle, timeout * 1000) == WAIT_TIMEOUT:
            kernel32.TerminateProcess(handle, 1)
            raise RuntimeError(
                f"El instalador no terminó en {timeout // 60} minutos y se ha cancelado."
            )
        code = wintypes.DWORD(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise RuntimeError("No se pudo leer el código de salida del instalador.")
        return int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def run_installer(installer: Path, args: list[str], requires_admin: bool) -> int:
    command = build_install_command(installer, args)
    log_message(f"Ejecutando: {' '.join(command)}")
    workdir = str(installer.parent)

    if requires_admin and not is_admin():
        if installer.suffix.lower() == ".msi":
            exe = "msiexec"
            params = " ".join(f'"{arg}"' for arg in command[1:])
        else:
            exe = str(installer)
            params = " ".join(f'"{arg}"' for arg in args)
        return _shell_execute_wait(exe, params, workdir)

    last_exc: OSError | None = None
    for attempt in range(3):
        try:
            completed = subprocess.run(
                command,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=INSTALLER_TIMEOUT,
                cwd=workdir,
            )
            return completed.returncode
        except OSError as exc:  # archivo aún bloqueado por el antivirus
            last_exc = exc
            time.sleep(2)
    raise RuntimeError(f"No se pudo ejecutar el instalador: {last_exc}")


def trigger_windows_update() -> str:
    """Abre Windows Update y pide un escaneo (UsoClient), informando de verdad."""
    parts: list[str] = []
    try:
        os.startfile("ms-settings:windowsupdate")
        parts.append("pantalla de Windows Update abierta")
    except OSError as exc:
        parts.append(f"no se pudo abrir Windows Update ({exc})")
    try:
        result = _run_hidden(["UsoClient.exe", "StartInteractiveScan"], timeout=30)
        if result.returncode == 0:
            parts.append("escaneo solicitado")
        else:
            parts.append(f"UsoClient devolvió {result.returncode}")
    except Exception:
        parts.append("UsoClient no disponible")
    return "Windows Update: " + "; ".join(parts)


class SetupPCApp:
    def __init__(self) -> None:
        start_session_log()
        self.root = Tk()
        self.root.withdraw()  # sin parpadeo mientras se aplica el tema
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1040x780")
        self.root.minsize(920, 660)
        apply_theme(self.root)
        self._set_window_icon()

        # La ventana aparece enseguida; la detección del equipo corre en segundo plano.
        self._splash = ttk.Label(
            self.root,
            text=">>> INICIANDO PRETELTOOLKIT\n[ DETECTANDO EL EQUIPO ]",
            font=(MONO, 12, "bold"),
            justify="center",
            padding=40,
        )
        self._splash.pack(expand=True)
        self.root.deiconify()

        self.programs, self.presets, self.download_dir = load_config()
        self.system_info = SystemInfo()
        self.gpu_names: list[str] = []
        self.vars: dict[str, BooleanVar] = {}
        self.running = False
        self.cancel_event = threading.Event()
        self._use_winget = False
        self._init_result: dict = {}
        self._init_thread = threading.Thread(target=self._detect_in_background, daemon=True)
        self._init_thread.start()
        self.root.after(150, self._poll_init)

    def _detect_in_background(self) -> None:
        try:
            self._init_result["info"] = detect_system_info()
        except Exception as exc:
            self._init_result["error"] = exc
        self._init_result["winget"] = winget_available()

    def _poll_init(self) -> None:
        if self._init_thread.is_alive():
            self.root.after(150, self._poll_init)
            return
        info = self._init_result.get("info")
        if info is None:
            info = SystemInfo(
                os_display=_windows_display_from_platform(),
                arch=platform.machine(),
                cpu=platform.processor(),
                admin=is_admin(),
            )
        self.system_info = info
        self.gpu_names = info.gpus
        self.prefer_winget = BooleanVar(value=bool(self._init_result.get("winget")))
        self._splash.destroy()
        self._build_ui()
        self._log_startup()
        error = self._init_result.get("error")
        if error:
            self.append_log(f"AVISO: la detección del equipo falló: {error}")

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
        for warning in _config_warnings:
            self.append_log(f"AVISO software.json: {warning}")

    def _build_scrollable_list(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent)
        container.pack(fill=BOTH, expand=True)

        canvas = Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=VERTICAL, command=canvas.yview)
        self.list_inner = ttk.Frame(canvas)
        self.list_inner.columnconfigure(0, weight=1)

        self.list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window = canvas.create_window((0, 0), window=self.list_inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
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
                self.list_inner, text=f">>> {category.upper()}", style="Head.TLabel"
            ).grid(row=row, column=0, sticky="w", pady=(14, 3), padx=4)
            row += 1
            Frame(self.list_inner, bg=LINE, height=1).grid(
                row=row, column=0, sticky="ew", padx=4
            )
            row += 1
            for program in categories[category]:
                var = BooleanVar(value=False)
                self.vars[program.id] = var
                item = ttk.Frame(self.list_inner)
                item.grid(row=row, column=0, sticky="w", padx=(12, 0), pady=(4, 0))
                ttk.Checkbutton(item, text=program.name, variable=var).pack(side=LEFT)

                tags: list[str] = []
                if program.winget_id:
                    tags.append("auto-update")
                if program.recommended:
                    tags.append("recomendado")
                color = DIM
                status = gpu_status(program, self.gpu_names)
                if status == "ok":
                    tags.append("[GPU detectada]")
                    color = FG
                elif status == "legacy":
                    tags.append("[GPU antigua: sin soporte, descarga manual]")
                    color = RED
                elif status == "other":
                    tags.append("[otra GPU]")
                if tags:
                    ttk.Label(
                        item,
                        text="  " + " · ".join(tags).upper(),
                        foreground=color,
                        font=(MONO, 8),
                    ).pack(side=LEFT)
                row += 1
                if program.description:
                    ttk.Label(
                        self.list_inner,
                        text=f"      {program.description}",
                        foreground=DIM,
                        font=(MONO, 8),
                        wraplength=860,
                    ).grid(row=row, column=0, sticky="w", padx=(28, 8))
                    row += 1

    def _build_ui(self) -> None:
        pad = 14

        # --- cabecera: título macro + metadatos, y regla roja gruesa ---
        header = Frame(self.root, bg=BG)
        header.pack(fill="x", padx=pad, pady=(12, 0))
        ttk.Label(header, text="PRETELTOOLKIT", style="Title.TLabel").pack(side=LEFT)
        ttk.Label(
            header,
            text=f"REV {APP_VERSION}  ®\nHERRAMIENTA DE TÉCNICO POST-FORMATEO",
            style="Meta.TLabel",
            justify=RIGHT,
        ).pack(side=RIGHT, anchor="s")
        Frame(self.root, bg=RED, height=3).pack(fill="x", padx=pad, pady=(6, 8))

        # --- PC detectado: tabla clave/valor + indicadores de estado ---
        detect = ttk.LabelFrame(self.root, text="[ PC DETECTADO ]", padding=(10, 8))
        detect.pack(fill=BOTH, padx=pad, pady=(0, 8))
        detect.columnconfigure(1, weight=1)

        info = self.system_info
        rows = [
            ("WINDOWS", f"{info.os_display}  ·  {info.arch}"),
            ("CPU", info.cpu or "—"),
            ("RAM", f"{info.ram_gb} GB" if info.ram_gb else "—"),
            ("GPU", gpu_vendor_label(info.gpus)),
            ("DISCO", info.disk_summary),
        ]
        for i, (key, value) in enumerate(rows):
            ttk.Label(detect, text=key, style="Meta.TLabel").grid(
                row=i, column=0, sticky="w", padx=(0, 18)
            )
            ttk.Label(detect, text=value).grid(row=i, column=1, sticky="w")
        ttk.Label(
            detect,
            text="■ ONLINE" if info.internet else "■ SIN CONEXIÓN",
            style="Ok.TLabel" if info.internet else "Err.TLabel",
        ).grid(row=0, column=2, sticky="e")
        ttk.Label(
            detect,
            text="■ ADMIN" if info.admin else "□ SIN ADMIN",
            style="Head.TLabel" if info.admin else "Meta.TLabel",
        ).grid(row=1, column=2, sticky="e")

        # --- barra de herramientas ---
        toolbar = ttk.Frame(self.root, padding=(pad, 0))
        toolbar.pack(fill=BOTH, pady=(0, 8))
        for text, command in (
            ("SELECCIONAR TODO", self.select_all),
            ("QUITAR TODO", self.select_none),
            ("DETECTAR DE NUEVO", self.refresh_system),
            ("EDITAR LISTA", self.open_config_info),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side=LEFT, padx=(0, 6))
        if not is_admin():
            ttk.Button(toolbar, text="EJECUTAR COMO ADMIN", command=self.request_admin).pack(
                side=RIGHT
            )

        if self.presets:
            preset_bar = ttk.LabelFrame(self.root, text="[ PERFILES DE INSTALACIÓN ]", padding=(10, 6))
            preset_bar.pack(fill=BOTH, padx=pad, pady=(0, 8))
            for preset in self.presets:
                ttk.Button(
                    preset_bar,
                    text=preset.name.upper(),
                    command=lambda p=preset: self.apply_preset(p),
                ).pack(side=LEFT, padx=(0, 6))

        opts = ttk.Frame(self.root, padding=(pad, 0, pad, 6))
        opts.pack(fill=BOTH)
        ttk.Checkbutton(
            opts,
            text="USAR WINGET SI ESTÁ DISPONIBLE (SIEMPRE LA ÚLTIMA VERSIÓN)",
            variable=self.prefer_winget,
        ).pack(side=LEFT)

        # --- cuerpo: lista de programas / registro ---
        body = ttk.Panedwindow(self.root, orient="vertical")
        body.pack(fill=BOTH, expand=True, padx=pad, pady=(0, 10))

        list_frame = ttk.LabelFrame(body, text="[ PROGRAMAS Y DRIVERS ]", padding=6)
        body.add(list_frame, weight=3)
        self._build_scrollable_list(list_frame)

        log_frame = ttk.LabelFrame(body, text="[ PROGRESO Y REGISTRO ]", padding=8)
        body.add(log_frame, weight=2)

        self.progress = ttk.Progressbar(log_frame, mode="determinate", maximum=100)
        self.progress.pack(fill=BOTH, pady=(0, 6))
        self.status_label = ttk.Label(log_frame, text="LISTO.", style="Meta.TLabel")
        self.status_label.pack(anchor="w", pady=(0, 4))

        text_container = Frame(log_frame, bg=BG)
        text_container.pack(fill=BOTH, expand=True)
        log_scroll = ttk.Scrollbar(text_container, orient=VERTICAL)
        log_scroll.pack(side=RIGHT, fill="y")
        self.log_text = Text(
            text_container,
            height=10,
            wrap="word",
            yscrollcommand=log_scroll.set,
            font=(MONO, 9),
            bg=BG,
            fg=FG,
            insertbackground=FG,
            selectbackground=RED,
            selectforeground="#FFFFFF",
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=LINE,
            padx=8,
            pady=6,
        )
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        log_scroll.config(command=self.log_text.yview)
        self.log_text.tag_configure("err", foreground=RED)
        self.log_text.tag_configure("head", font=(MONO, 9, "bold"))
        self.log_text.tag_configure("ok", font=(MONO, 9, "bold"))

        # --- acciones ---
        actions = ttk.Frame(self.root, padding=(pad, 0, pad, 12))
        actions.pack(fill=BOTH, side="bottom", before=body)

        self.pro_btn = ttk.Button(
            actions, text="INSTALACIÓN PROFESIONAL", style="Primary.TButton",
            command=self.start_professional,
        )
        self.pro_btn.pack(side=LEFT, padx=(0, 8))

        self.download_only_btn = ttk.Button(
            actions, text="SOLO DESCARGAR", command=lambda: self.start_work(install=False)
        )
        self.download_only_btn.pack(side=LEFT, padx=(0, 8))

        self.install_btn = ttk.Button(
            actions,
            text="DESCARGAR E INSTALAR",
            command=lambda: self.start_work(install=True),
        )
        self.install_btn.pack(side=LEFT, padx=(0, 8))

        self.cancel_btn = ttk.Button(
            actions, text="CANCELAR", command=self.cancel_work, state="disabled"
        )
        self.cancel_btn.pack(side=LEFT)

        ttk.Button(actions, text="ABRIR LOGS", command=self.open_logs).pack(side=RIGHT)
        ttk.Button(actions, text="ABRIR DOWNLOADS", command=self.open_downloads).pack(
            side=RIGHT, padx=(0, 8)
        )
        ttk.Button(actions, text="SALIR", command=self.root.destroy).pack(
            side=RIGHT, padx=(0, 8)
        )

    def append_log(self, message: str) -> None:
        if "[ERROR]" in message or "falló" in message:
            tag = "err"
        elif message.startswith(("---", "===")):
            tag = "head"
        elif message.startswith("[OK]"):
            tag = "ok"
        else:
            tag = ""
        self.log_text.insert(END, message + "\n", (tag,) if tag else ())
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
                status = gpu_status(program, self.gpu_names)
                if status == "ok":
                    self.vars[program.id].set(True)
                    applied += 1
                elif status == "legacy":
                    self.append_log(
                        f"AVISO: tu GPU es demasiado antigua para el driver '{program.name}'. "
                        "No se marca: descarga el driver adecuado a mano desde la web del fabricante."
                    )
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
        winget_available.cache_clear()
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
            if relaunch_as_admin():
                self.root.destroy()
            else:
                messagebox.showwarning(
                    "Administrador",
                    "No se concedieron permisos de administrador.\n"
                    "PretelToolkit sigue abierto sin administrador.",
                )

    def open_downloads(self) -> None:
        os.startfile(self.download_dir)

    def open_logs(self) -> None:
        os.startfile(LOGS_DIR)

    def open_config_info(self) -> None:
        info = Toplevel(self.root)
        info.configure(bg=BG)
        info.title("Editar lista")
        info.geometry("640x220")
        ttk.Label(info, text="EDITA PROGRAMAS Y PERFILES EN:", style="Meta.TLabel", padding=12).pack(anchor="w")
        ttk.Label(info, text=str(CONFIG_PATH), font=(MONO, 10)).pack(
            anchor="w", padx=12
        )
        ttk.Button(
            info,
            text="ABRIR CARPETA CONFIG",
            command=lambda: os.startfile(CONFIG_PATH.parent),
        ).pack(padx=12, pady=8, anchor="w")

    def start_professional(self) -> None:
        if self.running:
            return

        if not self.selected_programs():
            oficina = next(
                (p for p in self.presets if p.key in ("oficina", "pc_oficina", "pc_basico", "basico")),
                None,
            )
            if oficina is None:
                self.select_none()
                for program in self.programs:
                    if program.recommended and gpu_status(program, self.gpu_names) in ("any", "ok"):
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
        self._use_winget = bool(self.prefer_winget.get())
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
        self._use_winget = bool(self.prefer_winget.get())
        self.set_busy(True)
        threading.Thread(
            target=self._worker, args=(selected, install, False), daemon=True
        ).start()

    def _process_one(self, program: Program, install: bool) -> None:
        destination = self.download_dir / program.filename

        def block_legacy_gpu() -> None:
            if program.unsupported_url:
                webbrowser.open(program.unsupported_url)
            raise RuntimeError(
                "Tu GPU es demasiado antigua para el driver que incluye PretelToolkit. "
                "Descarga el driver adecuado a mano desde la web del fabricante "
                "(se ha abierto en el navegador)."
            )

        if gpu_status(program, self.gpu_names) == "legacy":
            block_legacy_gpu()

        if (
            install
            and self._use_winget
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
            raise RuntimeError(
                "Descarga manual necesaria: se ha abierto la web del fabricante; "
                "guarda el instalador en la carpeta downloads."
            )

        url = resolve_download_url(program, self.gpu_names)
        if (
            program.url_type == "nvidia_lookup"
            and url == program.url
            and gpu_is_legacy(program, self.gpu_names)
        ):
            # NVIDIA no respondió y el driver de respaldo no sirve para esta GPU.
            block_legacy_gpu()

        def progress_cb(percent: int, done: int, total_size: int) -> None:
            p = program
            if percent >= 0:
                self.root.after(0, lambda v=percent: self.progress.config(value=v))
                if total_size:
                    mb_done = done / 1048576
                    mb_total = total_size / 1048576
                    self.root.after(
                        0,
                        lambda pc=percent, md=mb_done, mt=mb_total: self.set_status(
                            f"Descargando {p.name}: {pc}% ({md:.1f}/{mt:.1f} MB)"
                        ),
                    )

        if cached_download_is_usable(destination, url):
            self.root.after(0, lambda: self.append_log(f"Ya descargado: {destination.name}"))
        else:
            if destination.exists():
                self.root.after(
                    0,
                    lambda: self.append_log(
                        f"{destination.name}: descarga anterior incompleta, de otra URL o "
                        "antigua; se descarga de nuevo."
                    ),
                )
            download_file(
                url,
                destination,
                progress_cb,
                self.cancel_event,
                user_agent=program.user_agent,
                referer=program.referer,
                sha256=program.sha256,
            )
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
        if code in INSTALL_OK_CODES:
            detail = INSTALL_OK_CODES[code]
            record_result(program.name, True, detail)
            self.root.after(0, lambda: self.append_log(f"[OK] {program.name} — {detail}"))
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
        reboot = any("reiniciar" in r.detail or "reinicio" in r.detail for r in _session_results)

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
        if reboot:
            self.root.after(
                0,
                lambda: self.append_log(
                    "AVISO: hay instalaciones que necesitan reiniciar Windows para terminar."
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

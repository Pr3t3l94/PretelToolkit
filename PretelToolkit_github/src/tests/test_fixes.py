import importlib.machinery, importlib.util, json, os, sys, tempfile, threading, time, http.server, socketserver, functools
from pathlib import Path

"""Pruebas de PretelToolkit. Uso:  python src\tests\test_fixes.py
(necesita Internet: prueba descargas locales, firmas de Windows y la API de NVIDIA).
Los logs y descargas de prueba van a una carpeta temporal, no al kit."""
HERE = Path(__file__).resolve().parent
SRC = str(HERE.parent / "setup_pc.pyw")
CONFIG = HERE.parent.parent / "config" / "software.json"
loader = importlib.machinery.SourceFileLoader("setup_pc", SRC)
spec = importlib.util.spec_from_loader("setup_pc", loader)
m = importlib.util.module_from_spec(spec)
sys.modules["setup_pc"] = m
loader.exec_module(m)

tmp = Path(tempfile.mkdtemp(prefix="pt_test_"))
m.BASE_DIR = tmp
m.LOGS_DIR = tmp / "logs"
(tmp / "downloads").mkdir()
dl = tmp / "downloads"
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK   {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {extra}")


print("== config")
orig_cfg = m.CONFIG_PATH
m.CONFIG_PATH = CONFIG
progs, presets, _ = m.load_config()
check("config carga 41 programas", len(progs) == 41, len(progs))
check("sin avisos de config", not m._config_warnings, m._config_warnings)
byid = {p.id: p for p in progs}
check("hwinfo manual", byid["hwinfo"].url_type == "manual_download")
check("sourceforge UA en winscp", byid["winscp"].user_agent == "curl/8.4.0")

# json roto -> mensaje claro
bad = tmp / "bad.json"
bad.write_text('{"programs": [ {"id": "a",, ] }', encoding="utf-8")
m.CONFIG_PATH = bad
try:
    m.load_config()
    check("json roto da error claro", False)
except RuntimeError as e:
    check("json roto da error claro", "línea" in str(e), str(e))
# entrada incompleta -> se ignora con aviso
inc = tmp / "inc.json"
inc.write_text(json.dumps({"programs": [{"id": "x", "name": "X"}, {"id": "ok", "name": "Ok", "url": "u", "filename": "f.exe"}]}), encoding="utf-8")
m.CONFIG_PATH = inc
progs2, _, _ = m.load_config()
check("entrada incompleta ignorada, resto carga", [p.id for p in progs2] == ["ok"] and len(m._config_warnings) == 1, m._config_warnings)
m.CONFIG_PATH = orig_cfg

print("== GPU antigua (regex NVIDIA)")
nv = byid["nvidia_app"]
cases = {
    "NVIDIA GeForce GT 730": "legacy",
    "NVIDIA GeForce GTX 650 Ti": "legacy",
    "NVIDIA GeForce GTX 780": "legacy",
    "NVIDIA GeForce GT 240": "legacy",
    "NVIDIA GeForce GTX 750 Ti": "ok",
    "NVIDIA GeForce GTX 970": "ok",
    "NVIDIA GeForce GTX 1060 6GB": "ok",
    "NVIDIA GeForce GT 1030": "ok",
    "NVIDIA GeForce RTX 3060": "ok",
    "Intel(R) UHD Graphics": "other",
}
for name, want in cases.items():
    if want == "legacy":
        got = m.gpu_is_legacy(nv, [name])
        check(f"{name} -> antigua (regex de respaldo)", got is True)
    elif want == "ok":
        check(f"{name} -> no antigua", not m.gpu_is_legacy(nv, [name]) and m.gpu_status(nv, [name]) == "ok")
    else:
        check(f"{name} -> otra marca", m.gpu_status(nv, [name]) == "other", m.gpu_status(nv, [name]))
check("GT730 + RTX3060 (dos GPUs) -> no antigua", not m.gpu_is_legacy(nv, ["NVIDIA GeForce GT 730", "NVIDIA GeForce RTX 3060"]))
check("con nvidia_lookup una GPU antigua se marca igualmente (ok)", nv.url_type == "nvidia_lookup" and m.gpu_status(nv, ["NVIDIA GeForce GT 730"]) == "ok")
import dataclasses
fixed = dataclasses.replace(nv, url_type=None)
check("sin nvidia_lookup (driver fijo) una GPU antigua -> legacy", m.gpu_status(fixed, ["NVIDIA GeForce GT 730"]) == "legacy")

print("== driver NVIDIA segun la GPU (API real de NVIDIA)")
def vkey(v): return tuple(int(x) for x in v.split("."))
for gpu, minv, maxv in [("NVIDIA GeForce GTX 970", "500", None), ("NVIDIA GeForce GTX 1060 6GB", "500", None),
                        ("NVIDIA GeForce GT 730", "470", "480"), ("NVIDIA GeForce RTX 3060 Laptop GPU", "500", None),
                        ("NVIDIA GeForce RTX 5070", "570", None)]:
    try:
        url, ver = m.resolve_nvidia_driver([gpu])
        ok = url.endswith(".exe") and vkey(ver) >= vkey(minv) and (maxv is None or vkey(ver) < vkey(maxv))
        check(f"{gpu} -> {ver}", ok, url)
    except Exception as e:
        check(f"{gpu}", False, repr(e))
url, ver = m.resolve_nvidia_driver(["Intel(R) UHD Graphics", "NVIDIA GeForce GTX 970"])
check("con iGPU Intel + NVIDIA usa la NVIDIA (GTX 970 -> 582.x)", vkey(ver) >= vkey("500"), ver)
import urllib.request as _ur
for gpu in ("NVIDIA GeForce GTX 970", "NVIDIA GeForce GT 730"):
    u, v = m.resolve_nvidia_driver([gpu])
    with _ur.urlopen(_ur.Request(u, headers={"User-Agent": m.DEFAULT_USER_AGENT}), timeout=30) as r:
        magic = r.read(2)
        size = int(r.headers.get("Content-Length", 0))
    check(f"la URL de NVIDIA para {gpu} ({v}) existe y es un .exe ({size/1e6:.0f} MB)", magic == b"MZ" and size > 100_000_000)
try:
    m.resolve_nvidia_driver(["NVIDIA (sin driver: Microsoft Basic Display Adapter)"])
    check("GPU sin modelo conocido -> error (usa el respaldo)", False)
except RuntimeError:
    check("GPU sin modelo conocido -> error (usa el respaldo)", True)
real_fetch = m._fetch_bytes
def _boom(*a, **k): raise OSError("sin red")
m._fetch_bytes = _boom
check("sin conexion con NVIDIA -> URL de respaldo del JSON", m.resolve_download_url(nv, ["NVIDIA GeForce GTX 970"]) == nv.url)
m._fetch_bytes = real_fetch
check("con conexion -> URL distinta de la de respaldo", m.resolve_download_url(nv, ["NVIDIA GeForce GTX 970"]) != nv.url)

print("== GPU sin driver (Basic Display Adapter)")
lab = m._gpu_label("Microsoft Basic Display Adapter", r"PCI\VEN_10DE&DEV_1C03&SUBSYS_...")
check("basic display + VEN_10DE -> NVIDIA", "NVIDIA" in lab and m.gpu_matches_filter(["nvidia"], [lab]), lab)
lab = m._gpu_label("Microsoft Basic Display Adapter", r"PCI\VEN_1002&DEV_67DF")
check("basic display + VEN_1002 -> AMD", m.gpu_matches_filter(["amd", "radeon"], [lab]), lab)
check("nombre normal no se toca", m._gpu_label("NVIDIA GeForce GTX 970", r"PCI\VEN_10DE") == "NVIDIA GeForce GTX 970")
check("virtual (sin VEN) no se toca", m._gpu_label("Microsoft Hyper-V Video", r"VMBUS\{x}") == "Microsoft Hyper-V Video")

print("== deteccion real (un solo PowerShell)")
t0 = time.time()
data = m._detect_via_powershell()
t1 = time.time() - t0
check("powershell devuelve datos", bool(data), data)
print("     ", json.dumps(data, ensure_ascii=False)[:400], f"({t1:.1f}s)")
t0 = time.time()
info = m.detect_system_info()
t2 = time.time() - t0
print("     ", info, f"({t2:.1f}s)")
check("CPU con nombre real (no 'Family 6 Model')", info.cpu and "Family" not in info.cpu, info.cpu)
check("RAM detectada", info.ram_gb > 0, info.ram_gb)
check("SO detectado", "Windows" in info.os_display, info.os_display)
check("GPU detectada", bool(info.gpus), info.gpus)
check("disco detectado", info.disk_summary not in ("", "Desconocido"), info.disk_summary)
check("internet", info.internet is True)

print("== esperar al instalador y codigo de salida (verb=open, sin UAC)")
t0 = time.time()
code = m._shell_execute_wait("cmd.exe", '/c "ping -n 3 127.0.0.1 >nul & exit 7"', str(tmp), verb="open")
dt = time.time() - t0
check("devuelve el codigo real (7)", code == 7, code)
check("ha esperado a que terminara (>=1.5 s)", dt >= 1.5, f"{dt:.2f}s")
check("3010 se devuelve tal cual", m._shell_execute_wait("cmd.exe", "/c exit 3010", str(tmp), verb="open") == 3010)
try:
    m._shell_execute_wait("C:\\no_existe_xyz.exe", "", str(tmp), verb="open")
    check("exe inexistente -> error", False)
except RuntimeError as e:
    check("exe inexistente -> error (tras reintentos)", "error" in str(e).lower(), str(e))
try:
    m._shell_execute_wait("cmd.exe", "/c ping -n 6 127.0.0.1 >nul", str(tmp), verb="open", timeout=1)
    check("timeout cancela y avisa", False)
except RuntimeError as e:
    check("timeout cancela y avisa", "no terminó" in str(e), str(e))

print("== codigos de salida")
for c, ok in [(0, True), (3010, True), (1641, True), (1638, True), (1603, False), (5, False)]:
    check(f"codigo {c} -> {'OK' if ok else 'ERROR'}", (c in m.INSTALL_OK_CODES) == ok)

print("== descargas: .part, validacion y cache")
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/good.exe":
            body = b"MZ" + b"\x90" * 5000
        elif self.path == "/page.exe":
            body = b"<!doctype html><html>" + b"x" * 5000
        elif self.path == "/short.exe":
            self.send_response(200); self.send_header("Content-Length", "9000"); self.end_headers()
            self.wfile.write(b"MZ" + b"\x00" * 100); return
        elif self.path == "/slow.exe":
            self.send_response(200); self.send_header("Content-Length", str(3 * 262144 + 2)); self.end_headers()
            for _ in range(3):
                self.wfile.write(b"MZ" + b"\x00" * (262144 - 2)); self.wfile.flush(); time.sleep(0.4)
            self.wfile.write(b"ab"); return
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
noop = lambda *a: None
ev = threading.Event()

dest = dl / "good.exe"
m.download_file(base + "/good.exe", dest, noop, ev)
check("descarga buena existe y sin .part", dest.exists() and not (dl / "good.exe.part").exists())
check("cache usable (misma URL)", m.cached_download_is_usable(dest, base + "/good.exe"))
check("cache NO usable si cambia la URL", not m.cached_download_is_usable(dest, base + "/otra.exe"))
dest.write_bytes(dest.read_bytes()[:3000])
check("cache NO usable si el archivo esta truncado", not m.cached_download_is_usable(dest, base + "/good.exe"))
m.download_file(base + "/good.exe", dest, noop, ev)
old = time.time() - 20 * 86400
os.utime(dest, (old, old))
check("cache NO usable si es muy antigua (>14 dias)", not m.cached_download_is_usable(dest, base + "/good.exe"))
legacy = dl / "legacy.exe"
legacy.write_bytes(b"MZ" + b"\x00" * 5000)
check("archivo viejo sin indice NO se reutiliza", not m.cached_download_is_usable(legacy, base + "/good.exe"))

page = dl / "page.exe"
try:
    m.download_file(base + "/page.exe", page, noop, ev)
    check("pagina HTML rechazada", False)
except RuntimeError as e:
    check("pagina HTML rechazada y sin restos", "parece una página web" in str(e) and not page.exists() and not (dl / "page.exe.part").exists(), str(e))
short = dl / "short.exe"
try:
    m.download_file(base + "/short.exe", short, noop, ev)
    check("descarga cortada detectada", False)
except Exception as e:
    check("descarga cortada detectada y sin restos", not short.exists() and not (dl / "short.exe.part").exists(), repr(e))
slow = dl / "slow.exe"
ev2 = threading.Event()
threading.Timer(0.6, ev2.set).start()
try:
    m.download_file(base + "/slow.exe", slow, noop, ev2)
    check("cancelacion", False)
except RuntimeError as e:
    check("cancelar deja sin archivo final ni .part", "cancelada" in str(e) and not slow.exists() and not (dl / "slow.exe.part").exists(), str(e))
srv.shutdown()

print("== verificacion de firma / hash")
st, subj = m._authenticode_status(Path(r"C:\Windows\System32\notepad.exe"))
check("notepad.exe firma Valid", st == "Valid", (st, subj))
unsigned = dl / "unsigned.exe"
unsigned.write_bytes(b"MZ" + b"\x00" * 3000)
st, _ = m._authenticode_status(unsigned)
check("exe sin firma no es Valid", st != "Valid", st)
m.verify_download(unsigned, None)
check("sin firma solo avisa (no borra)", unsigned.exists())
try:
    m.verify_download(unsigned, "0" * 64)
    check("sha256 incorrecto rechazado", False)
except RuntimeError:
    check("sha256 incorrecto rechazado y borrado", not unsigned.exists())
import hashlib
good = dl / "h.exe"
good.write_bytes(b"MZ" + b"\x01" * 3000)
m.verify_download(good, hashlib.sha256(good.read_bytes()).hexdigest())
check("sha256 correcto aceptado", good.exists())

print("== internet / winget cache / log")
check("check_internet", m.check_internet() is True)
m.winget_available.cache_clear()
a = m.winget_available(); b = m.winget_available()
check("winget_available cacheado", m.winget_available.cache_info().hits >= 1)
m.log_message("prueba")
sl = (m.LOGS_DIR / "setup.log").read_text(encoding="utf-8")
check("setup.log lleva fecha completa", sl.startswith("[20") and "prueba" in sl, sl[:40])

print("== relaunch_as_admin devuelve bool (no se ejecuta)")
check("firma", m.relaunch_as_admin.__annotations__.get("return") in ("bool", bool))

print(f"\nRESULTADO: {passed} OK, {failed} FALLOS")
sys.exit(1 if failed else 0)

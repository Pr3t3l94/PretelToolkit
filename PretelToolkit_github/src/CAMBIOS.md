# PretelToolkit — cambios de v3.0.0 a v3.1.0

Código fuente reconstruido desde el .exe original (`original_reconstruido.pyw` es la versión v3.0.0
tal cual; `original\PretelToolkit_v3.0.0.exe` es el ejecutable original) y corregido en `setup_pc.pyw`.

## Compilar y probar
- Compilar: `powershell -ExecutionPolicy Bypass -File src\compilar.ps1` (`-NoDeploy`, `-Consola`).
- Probar:   `python src\tests\test_fixes.py` (70 pruebas; necesita Internet).
- **Ejecuta el programa desde una copia fuera de esta carpeta** si el `.exe` da "Could not create
  temporary directory!": la carpeta puede llevar una etiqueta de integridad baja que heredan los
  archivos nuevos (ver aviso de `compilar.ps1`).

## Fallos corregidos
1. **Falsos "instalado" sin admin.** `run_installer` ahora espera al instalador elevado
   (`ShellExecuteEx` + espera) y usa su código de salida real; UAC cancelado = error claro.
2. **Códigos de salida.** 0, 3010, 1641 y 1638 cuentan como éxito (avisa si hay que reiniciar).
3. **Caché de descargas.** Se descarga a `.part`, se valida y se renombra; la caché solo se
   reutiliza si es de la misma URL, mismo tamaño, tiene <14 días y parece un instalador.
4. **URLs rotas** (software.json): Epic y Malwarebytes corregidas; CrystalDisk/WinSCP con User-Agent
   de curl (SourceForge); Adobe, HWiNFO, FileZilla, GPU-Z, WhatsApp y AMD pasan a descarga manual.
5. **Drivers GPU.** Detección por identificador PCI (aunque sea "Microsoft Basic Display Adapter").
   NVIDIA: se consulta la API oficial de NVIDIA y se descarga el driver más reciente compatible con
   la GPU (GTX 970 → 582.78, GT 730 → 475.14, RTX 50 → 617.14…); si falla, usa el de software.json
   y bloquea con aviso si la GPU es demasiado antigua para él.
6. **"Ejecutar como admin"** ya no cierra el programa si cancelas el UAC, y relanza con su propia
   carpeta temporal (antes heredaba la del proceso padre).
7. **CPU/RAM en Windows 11 24H2** (sin `wmic`): una sola llamada a PowerShell/CIM.
8. **Arranque rápido**: la ventana aparece al instante y la detección va en segundo plano.

## Menores
- `check_internet` prueba 443/53/80. `trigger_windows_update` informa de lo que hizo.
- Verificación de firma digital (Authenticode) y SHA-256 opcional (`"sha256"` en software.json).
- `software.json` roto → mensaje con línea/columna; entrada incompleta → se ignora con aviso.
- `setup.log` con fecha completa y rotación a 1 MB. Instaladores se ejecutan desde `downloads`
  (el `debug.log` de Chrome ya no cae en la raíz). Reintentos si el antivirus bloquea el archivo.

## Aspecto (interfaz)
Tema "telemetría táctica": modo oscuro (`#0A0A0A`/`#EAEAEA`), un único acento rojo (`#E61919`), verde solo
en el indicador ONLINE, Consolas en datos y Arial Black en el título, esquinas rectas, líneas de 1 px,
paneles con corchetes `[ ... ]`, categorías con `>>>`, botones planos que se invierten al pasar el ratón
y registro con errores en rojo. Todo está en `apply_theme()` y `_build_*` de `setup_pc.pyw` (constantes
`BG`, `FG`, `RED`… al principio). Para volver al aspecto anterior: `PretelToolkit.exe.bak`.

## Campos nuevos opcionales en software.json
`user_agent`, `referer`, `sha256`, `unsupported_gpu_regex`, `unsupported_url`,
`url_type: "nvidia_lookup"` (además de `manual_download`, `adobe_reader`, `malwarebytes`).

## Pendiente / limitaciones conocidas
- La instalación elevada con el UAC real no se ha probado de punta a punta (solo la espera y el
  código de salida con procesos de prueba).
- Si el PC no tiene driver de GPU y Windows no da el modelo ("Basic Display Adapter"), NVIDIA usa el
  driver de respaldo de software.json (566.36): sirve para GTX 900 en adelante hasta RTX 40.
- HWiNFO, FileZilla, GPU-Z, AMD, Adobe Reader y WhatsApp requieren descarga manual si no hay winget.

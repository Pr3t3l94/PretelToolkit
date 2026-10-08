# PretelToolkit

**Prepara un PC recién formateado en menos tiempo.**

PretelToolkit es una herramienta gratuita para técnicos y usuarios avanzados que automatiza la instalación de programas habituales y drivers de gráficos en equipos Windows. Elige un perfil, personaliza la selección y deja que la aplicación gestione las descargas y los instaladores.

- **Sistema:** Windows 10 y Windows 11
- **Interfaz:** español, creada con Python y Tkinter
- **Versión del código:** 3.1.0
- **Catálogo:** editable; añadir o quitar programas no requiere recompilar

## Funciones

- Instala programas desde un catálogo de configuración JSON, usando `winget` cuando está disponible y la descarga configurada como alternativa.
- Incluye perfiles para PC Básico, Oficina, Gaming, Técnico, drivers de gráficos y selección personalizada.
- Detecta la GPU mediante su identificador PCI y ayuda a obtener el controlador adecuado para NVIDIA, AMD o Intel.
- Comprueba las descargas antes de usarlas y admite validación de firma Authenticode y SHA-256 opcional.
- Gestiona instaladores elevados, códigos de salida y avisos de reinicio.
- Muestra información del equipo: procesador, memoria, GPU, discos, versión de Windows y conexión a Internet.
- Guarda registros e informes en `logs/`.

## Programas

El catálogo incluye utilidades de ofimática, navegadores, compresión, reproducción multimedia, diagnóstico, redes y seguridad, además de aplicaciones de comunicación y juegos. Entre otras: LibreOffice, Chrome, Firefox, 7-Zip, VLC, Notepad++, CPU-Z, GPU-Z, HWiNFO, CrystalDiskInfo, Rufus, Malwarebytes, Steam y Discord.

La lista completa y los perfiles están en [`config/software.json`](config/software.json). Puedes modificar los programas, sus parámetros de instalación y los perfiles desde ese archivo.

## Uso

### Ejecutable portable

Descarga `PretelToolkit.exe` desde la sección **Releases** (cuando haya una versión publicada) y colócalo junto a la carpeta `config/`. Ejecuta la aplicación y selecciona un perfil o marca los programas que quieras instalar. Windows puede solicitar permisos de administrador para algunos instaladores.

Si aparece el mensaje *“Could not create temporary directory!”*, copia el ejecutable a otra carpeta local e inténtalo de nuevo.

### Ejecutar desde el código fuente

Necesitas Windows 10/11 y Python 3.12. Desde la carpeta del proyecto, ejecuta:

```powershell
python src\setup_pc.pyw
```

## Desarrollo

Ejecutar las pruebas:

```powershell
python src\tests\test_fixes.py
```

Compilar el ejecutable con PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File src\compilar.ps1
```

## Estructura del proyecto

```text
src/setup_pc.pyw      aplicación principal
src/compilar.ps1      script de compilación
src/tests/            pruebas
src/CAMBIOS.md        historial de cambios
config/software.json  catálogo y perfiles
assets/               recursos gráficos
```

## Historial

La versión 3.1.0 reconstruye la aplicación a partir del ejecutable 3.0.0 y corrige, entre otros aspectos, falsos estados de instalación, URLs, detección de GPU y compatibilidad con Windows 11 24H2. Consulta [`src/CAMBIOS.md`](src/CAMBIOS.md) para ver los detalles.

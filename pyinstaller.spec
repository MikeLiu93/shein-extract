# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SheinExtract — produces dist/SheinExtract.exe.

Build with:
    pyinstaller pyinstaller.spec --clean --noconfirm

Outputs a single console-mode .exe (employees see a console window with
progress, per Mike's Q6). Hidden imports cover modules pulled in lazily
by openpyxl / requests that PyInstaller's static analysis sometimes misses.
"""

block_cipher = None

a = Analysis(
    ['app_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # No external data files — all assets are inline in shein_scraper.py
    ],
    hiddenimports=[
        # openpyxl pulls these dynamically when reading/writing
        'openpyxl.styles.alignment',
        'openpyxl.styles.borders',
        'openpyxl.styles.fills',
        'openpyxl.styles.fonts',
        'openpyxl.drawing.image',
        # PIL is required by openpyxl's image support (we ship it in requirements)
        'PIL',
        'PIL.Image',
        # tkinter — the wizard
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        # websocket-client uses these
        'websocket._abnf',
        'websocket._app',
        'websocket._core',
        'websocket._exceptions',
        'websocket._handshake',
        'websocket._http',
        'websocket._logging',
        'websocket._socket',
        'websocket._ssl_compat',
        'websocket._url',
        'websocket._utils',
        # our own modules
        'config',
        'shein_scraper',
        'run_excel',
        'notify',
        'setup_wizard',
        'update_check',
        'version',
        # Optional — only present after make_key_store.py ran
        'key_store',
        # check_stock and merge_master are run via separate .cmd shims, not
        # wired into app_main, but keep them importable for ad-hoc use.
        'check_stock',
        'merge_master',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim things we don't need (saves ~30MB)
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SheinExtract',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX compression skipped — Defender flags compressed PyInstaller exes more often
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,         # employees see the progress console (Mike Q6)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='resources\\app.ico',  # add later if you have an icon
)

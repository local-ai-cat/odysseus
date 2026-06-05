# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('/Users/timapple/Documents/Guest/odysseus/static', 'static'), ('/Users/timapple/Documents/Guest/odysseus/data', 'data'), ('/Users/timapple/Documents/Guest/odysseus/config', 'config')]
binaries = []
hiddenimports = ['chromadb_rust_bindings', 'app', 'uvicorn.lifespan.on', 'uvicorn.lifespan.off', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio']
datas += collect_data_files('certifi')
hiddenimports += collect_submodules('core')
hiddenimports += collect_submodules('routes')
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('services')
hiddenimports += collect_submodules('companion')
hiddenimports += collect_submodules('integrations')
hiddenimports += collect_submodules('mcp_servers')
hiddenimports += collect_submodules('kubernetes')
tmp_ret = collect_all('uvicorn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fastembed')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('chromadb')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('chromadb_rust_bindings')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tokenizers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('huggingface_hub')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['../../../guest/odysseus/packaging/desktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Odysseus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Odysseus',
)
app = BUNDLE(
    coll,
    name='Odysseus.app',
    icon=None,
    bundle_identifier='com.spike.odysseus',
)

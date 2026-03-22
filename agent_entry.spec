# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct

block_cipher = None

import os

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 1, 5, 0),
        prodvers=(1, 1, 5, 0),
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
    ),
    kids=[
        StringFileInfo([
            StringTable('040904B0', [
                StringStruct('CompanyName', 'Render Manager'),
                StringStruct('FileDescription', 'Render Manager Agent'),
                StringStruct('FileVersion', '1.1.5'),
                StringStruct('InternalName', 'RenderManager'),
                StringStruct('LegalCopyright', '© 2025-2026 Render Manager. All rights reserved.'),
                StringStruct('OriginalFilename', 'RenderManager.exe'),
                StringStruct('ProductName', 'Render Manager'),
                StringStruct('ProductVersion', '1.1.5'),
            ])
        ]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)
datas = [
    ('agent/assets', 'agent/assets'), 
    ('blender_addon', 'blender_addon'),
    ('agent/bin', 'agent/bin'),
    ('ThirdPartyNotices.txt', '.'),
    ('EULA.txt', '.')
]
if os.path.isdir('example_blend'):
    datas.append(('example_blend', 'example_blend'))

a = Analysis(
    ['agent_entry.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'aiohttp', 'colorama', 'keyring', 'rich', 'requests', 'dotenv', 'pydantic',
        'customtkinter', 'pystray', 'PIL', 'PIL._tkinter_finder',
    ] + collect_submodules('agent'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RenderManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='agent/assets/gradient_icon_256_transparent.ico',
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RenderManager',
)

# -*- mode: python ; coding: utf-8 -*-
import os
import shutil

block_cipher = None

# 清理可能存在的config.json，确保不会被打包
project_config = os.path.join('resources', 'config', 'config.json')
config_existed = False
config_backup_path = None

if os.path.exists(project_config):
    print(f"WARNING: Found {project_config} - this file should not be bundled!")
    # 备份并删除
    config_backup_path = project_config + '.backup'
    shutil.copy2(project_config, config_backup_path)
    os.remove(project_config)
    config_existed = True
    print(f"Moved {project_config} to {config_backup_path}")

a = Analysis(
    ['src\\main.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        ('resources/characters', 'resources/characters'),
        ('resources/scenes', 'resources/scenes'),
        ('resources/workflows', 'resources/workflows'),
        ('resources/icons', 'resources/icons'),
        ('resources/templates', 'resources/templates'),
        ('dragonli.ico', '.'),
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'openai',
        'requests',
        'PIL',
        'numpy',
        'numpy._core._exceptions',
        'numpy._core.multiarray',
        'numpy._core.umath',
        'numpy._core.numeric',
        'numpy._core.shape_base',
        'numpy._core.fromnumeric',
        'numpy._core._methods',
        'numpy._core.arrayprint',
        'numpy._core.defchararray',
        'numpy._core.records',
        'numpy._core.memmap',
        'numpy._core.function_base',
        'numpy._core.machar',
        'numpy._core.getlimits',
        'numpy._core._asarray',
        'numpy._core._ufunc_config',
        'numpy._core._dtype',
        'numpy._core._dtype_ctypes',
        'numpy._core._add_newdocs',
        'numpy._core._multiarray_tests',
        'numpy._core._string_helpers',
        'numpy._core._type_aliases',
        'numpy._core._multiarray_umath',
        'cv2',
        'ffmpeg',
        'pydub',
        'imageio_ffmpeg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'jupyter',
        'IPython',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 严格排除所有config.json文件
a.datas = [x for x in a.datas if 'config.json' not in str(x[0]).lower()]

# 手动添加安全的配置文件
a.datas.append(('resources/config/config.example.json', 'resources/config/config.example.json', 'DATA'))
a.datas.append(('resources/config/pronunciation_dict.json', 'resources/config/pronunciation_dict.json', 'DATA'))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Dragonli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='dragonli.ico',
)

# 打包完成后恢复config.json（如果有备份）
if config_existed and config_backup_path and os.path.exists(config_backup_path):
    shutil.copy2(config_backup_path, project_config)
    os.remove(config_backup_path)
    print(f"Restored {project_config} from backup")

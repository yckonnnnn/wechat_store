# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将微信小店客服系统打包成 Windows 可执行文件

使用方法：
pyinstaller weixin_store.spec
"""

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# 收集所有需要的数据文件
config_files = [
    ('config/image_categories.json', 'config/image_categories.json'),
    ('config/address.json', 'config/address.json'),
    ('config/reply_templates.json', 'config/reply_templates.json'),
    ('config/media_whitelist.json', 'config/media_whitelist.json'),
    ('config/knowledge_base.json', 'config/knowledge_base.json'),
    ('config/model_settings.json', 'config/model_settings.json'),
]

# 收集 docs 目录下的系统提示词文件
docs_files = [
    ('docs/system_prompt_private_ai_customer_service.md', 'docs/system_prompt_private_ai_customer_service.md'),
    ('docs/private_ai_customer_service_playbook.md', 'docs/private_ai_customer_service_playbook.md'),
]

# 合并所有数据文件
datas = config_files + docs_files

# PySide6 需要额外收集
binaries = []

# 收集 PySide6 相关资源
datas += collect_all('PySide6')[1]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # PySide6 相关
        'PySide6',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        # 其他隐藏导入
        'src',
        'src.ui',
        'src.ui.main_window',
        'src.ui.browser_tab',
        'src.ui.knowledge_tab',
        'src.ui.model_config_tab',
        'src.ui.agent_status_tab',
        'src.ui.image_management_tab',
        'src.ui.crm_manager_tab',
        'src.ui.left_panel',
        'src.core',
        'src.core.session_manager',
        'src.core.message_processor',
        'src.core.private_cs_agent',
        'src.services',
        'src.services.llm_service',
        'src.services.browser_service',
        'src.services.knowledge_service',
        'src.services.rag_service',
        'src.services.conversation_logger',
        'src.services.crm_contact_service',
        'src.data',
        'src.data.config_manager',
        'src.data.knowledge_repository',
        'src.data.memory_store',
        'src.utils',
        'src.utils.constants',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'test',
        'tests',
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
    [],
    exclude_binaries=True,
    name='微信小店客服助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 设置为 False 以隐藏控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加 .ico 文件作为程序图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='微信小店客服助手',
)

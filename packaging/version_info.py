"""Scrive il file di versione di Windows per PyInstaller (--version-file).

Nome del prodotto e versione finiscono nelle proprietà del .exe: la firma di
SignPath li controlla.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from openwisp_voucher import __version__  # noqa: E402

numbers = tuple(int(n) for n in __version__.split(".")[:3]) + (0,)

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={n}, prodvers={n}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Michele Salerno'),
      StringStruct('FileDescription', 'openwisp-voucher'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'openwisp-voucher'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'openwisp-voucher.exe'),
      StringStruct('ProductName', 'openwisp-voucher'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

Path(sys.argv[1]).write_text(TEMPLATE.format(n=numbers, v=__version__), encoding="utf-8")

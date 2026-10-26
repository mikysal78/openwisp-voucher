import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import i18n, store


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("openwisp-voucher")
    app.setOrganizationName("NINUX")
    i18n.set_language(store.load_settings().language)
    # import dopo la lingua: alcune etichette sono costanti di classe
    from .ui import MainWindow

    icon = QIcon(str(Path(__file__).with_name("icon.png")))
    app.setWindowIcon(icon)
    window = MainWindow(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

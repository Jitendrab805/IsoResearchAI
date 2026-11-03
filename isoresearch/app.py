"""Application entry point."""
from __future__ import annotations

import logging
import os
import sys
import traceback


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if sys.platform.startswith("win"):
        try:  # crisp text on high-DPI displays + own taskbar icon
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IsoResearchAI.Desktop")
        except Exception:  # noqa: BLE001
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    # QtWebEngine is not used; make sure Qt never tries to reach the network for anything.
    os.environ.setdefault("QT_NETWORK_ACCESS_DISABLED", "1")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .context import AppContext
    from .ui.icons import logo_icon
    from .ui.main_window import MainWindow
    from .ui.state import AppState

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("IsoResearchAI")
    app.setWindowIcon(logo_icon())
    try:
        ctx = AppContext.create(enforce_offline=True)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, APP_NAME, f"IsoResearch AI could not start:\n\n{exc}\n\n"
                             + "".join(traceback.format_exception_only(exc)))
        return 1

    def excepthook(et, ev, tb):
        logging.getLogger("isoresearch").error("Unhandled error", exc_info=(et, ev, tb))
        QMessageBox.warning(None, APP_NAME, f"An unexpected error occurred:\n{et.__name__}: {ev}\n\n"
                            "Details were written to the log file (Settings → Logs). Your data is safe.")

    sys.excepthook = excepthook
    state = AppState(ctx)
    win = MainWindow(state)
    win.show()
    if "--smoke-test" in argv:  # used by tests / CI: start, render, then quit
        from PySide6.QtCore import QTimer

        QTimer.singleShot(int(os.environ.get("ISORESEARCH_SMOKE_MS", "2500")), app.quit)
    code = app.exec()
    ctx.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())

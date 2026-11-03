"""GUI tests (run offscreen).  They check that the window launches, pages
work, the GUI stays responsive during long tasks and the missing-model path
never fabricates an answer."""
import os
import socket
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import PAPER_A, make_pdf  # noqa: E402
from mock_ollama import MockOllama  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        pump(50)
        if cond():
            return True
    return False


@pytest.fixture()
def window(qapp, app_ctx):
    from isoresearch.ui.main_window import MainWindow
    from isoresearch.ui.state import AppState

    st = AppState(app_ctx)
    w = MainWindow(st)
    w.show()
    pump(200)
    yield w, st
    w.close()
    pump(100)


def test_window_launches_and_all_pages_render(window):
    w, st = window
    assert w.isVisible() and w.windowTitle() == "IsoResearch AI"
    for key in ("chat", "history", "library", "literature", "gaps", "plots", "data", "references", "settings"):
        w.navigate(key)
        pump(50)
        assert w.stack.currentWidget() is w.pages[key]
    for theme in ("light", "dark"):
        st.ctx.settings.set("ui.theme", theme)
        w.apply_theme()
        pump(30)


def test_gui_responsive_during_import(window, tmp_path):
    w, st = window
    long_pages = PAPER_A["pages"] * 8  # 24-page synthetic papers so the import takes a noticeable time
    for i in range(25):
        make_pdf(tmp_path / f"p{i}.pdf", {**PAPER_A, "title": f"Synthetic paper {i}", "pages": long_pages})
    lib = w.pages["library"]
    ticks, gaps = [], []
    last = [time.perf_counter()]

    def tick():
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
        ticks.append(now)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)
    lib.import_paths([tmp_path])
    assert wait_until(lambda: lib.task is None, 120)
    timer.stop()
    assert st.ctx.repo.counts()["total"] == 25
    assert len(ticks) >= 5  # the timer kept firing while the worker imported
    print(f"max event-loop gap {max(gaps):.3f}s over {len(ticks)} ticks")
    assert max(gaps) < 0.5, f"event loop blocked for {max(gaps):.2f}s"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_chat_without_model_shows_error_and_library_results(window, pdfs):
    w, st = window
    st.ctx.importer.import_paths([pdfs["a"]])
    st.ctx.settings.set("llm.base_url", f"http://127.0.0.1:{_free_port()}")
    st.ctx.settings.set("llm.model", "llama3.1:8b")
    st.ctx.reload_llm()
    chat = w.pages["chat"]
    chat.ask_external("What controls the amount effect in heavy rain?")
    assert wait_until(lambda: chat.task is None, 20)
    from isoresearch.ui.widgets.chat_widgets import MessageBubble

    bubbles = chat.view.inner.findChildren(MessageBubble)
    roles = [b.role for b in bubbles]
    assert "error" in roles and "library" in roles and "assistant" not in roles
    err = [b for b in bubbles if b.role == "error"][0]
    assert "never fabricates" in err.view.toPlainText()
    assert st.ctx.chat.store.messages(chat.conv_id) == []


def test_chat_streams_cited_answer_and_stop(window, pdfs):
    w, st = window
    st.ctx.importer.import_paths([pdfs["a"]])
    with MockOllama("Heavy rain was depleted [S1] " + "more " * 300, delay=0.004) as mo:
        st.ctx.settings.set("llm.base_url", mo.url)
        st.ctx.settings.set("llm.model", "mock")
        st.ctx.reload_llm()
        chat = w.pages["chat"]
        chat.ask_external("What controls the amount effect in heavy rain?")
        assert wait_until(lambda: chat.stream_bubble is not None, 15)
        pump(200)
        chat.stop()
        assert wait_until(lambda: chat.task is None, 15)
    msgs = st.ctx.chat.store.messages(chat.conv_id)
    assert msgs[-1]["role"] == "assistant"
    assert "stopped by user" in msgs[-1]["content"]
    assert "[S1]" in msgs[-1]["content"] and any(c["used"] for c in msgs[-1]["citations"])


def test_pdf_viewer_opens_at_page(qapp, app_ctx, pdfs):
    from isoresearch.ui.pdf_viewer import HAVE_QTPDF, PdfViewer

    if not HAVE_QTPDF:
        pytest.skip("QtPdf not available")
    r = app_ctx.importer.import_file(pdfs["a"])
    d = app_ctx.repo.document(r.doc_id)
    v = PdfViewer(d["stored_path"], 3, "t")
    v.show()
    pump(300)
    assert v.doc.pageCount() == 3 and v.spin.value() == 3
    v.close()


def test_workspaces_end_to_end_without_ai(window, pdfs, tmp_path):
    """Literature scan, gap analysis (no AI), data loading, plot preview and export through the GUI."""
    from isoresearch.ui.pages.gaps_page import GapCard

    w, st = window
    st.ctx.importer.import_paths([pdfs["a"], pdfs["b"]])
    st.library_changed.emit()
    lit = w.pages["literature"]
    lit._check_all(True)
    lit.scan_checked()
    assert wait_until(lambda: lit.task is None, 20)
    lit.papers.setCurrentRow(0)
    assert lit.rec.rowCount() > 10
    lit.build_table()
    assert lit.cmp.rowCount() == 2
    first = st.ctx.repo.documents()[0]["id"]
    lit.lit.edit_field(first, "limitations", "Only one monsoon season was sampled")
    gaps = w.pages["gaps"]
    gaps.use_llm.setChecked(False)
    gaps.analyse()
    assert wait_until(lambda: gaps.task is None, 20)
    pump(100)
    assert gaps.inner.findChildren(GapCard)
    data = w.pages["data"]
    data.load_example()
    assert wait_until(lambda: st.dataset is not None, 20)
    data.apply_mapping()
    plots = w.pages["plots"]
    w.navigate("plots")
    plots.catalog.setCurrentRow(1)
    assert plots.render_btn.isEnabled()
    plots.preview()
    assert wait_until(lambda: plots.current_fig is not None, 20)
    st.ctx.paths.figures_dir.mkdir(exist_ok=True)
    from isoresearch.plotting.render import export_figure

    out = export_figure(plots.current_fig, plots.result, plots.spec, plots.opts, st.mapping, str(st.dataset.path),
                        tmp_path, ("png",), 120)
    assert (tmp_path / out["folder"]).exists()

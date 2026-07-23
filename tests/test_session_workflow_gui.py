import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from acceptance_checker.gui import AcceptanceCheckerWindow, SessionWorkflowWidget
from tests.test_session_workflow import build_workflow_files


def test_formal_session_is_default_gui_and_quick_check_is_explicit(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = AcceptanceCheckerWindow()
    assert window.mode_tabs.currentIndex() == 0
    assert "v4 Session 候選流程" in window.mode_tabs.tabText(0)
    assert "非完整 v4" in window.mode_tabs.tabText(1)
    assert window.session_workflow.pages.count() == 6
    app.processEvents()
    window.close()


def test_session_widget_runs_manifest_to_judgment(tmp_path):
    app = QApplication.instance() or QApplication([])
    manifest, package, _image = build_workflow_files(tmp_path)
    widget = SessionWorkflowWidget()
    widget.load_manifest(str(manifest))
    widget.check_evidence()
    widget.execute_measurements(str(package))
    widget.judge_session()
    app.processEvents()

    assert widget.group_table.rowCount() == 6
    assert widget.trace_table.rowCount() == 46
    assert "accepted" in widget.decision_view.toPlainText()
    assert widget.btn_report.isEnabled()
    assert widget.gap_table.item(0, 2).text() == "目前沒有已知證據缺口"
    widget.close()

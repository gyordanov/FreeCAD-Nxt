"""The inspector in the Tasks panel's idle page, with a stand-in task view.

Run with: python3 tests/test_tasks_inspector.py
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


import fakes  # noqa: E402
import shiboken6  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
App, Gui = fakes.install()

from freecad.nxt.inspector import host  # noqa: E402
from freecad.nxt.tools import task_layout, tasks_inspector  # noqa: E402


class Bridge(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.running = False
        self.title = ""

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


class Tasks(QtWidgets.QStackedWidget):
    """FreeCAD's task view: the idle panel is page 0, a dialog a page."""

    def __init__(self) -> None:
        super().__init__()
        page = QtWidgets.QWidget()
        self.main = QtWidgets.QVBoxLayout(page)
        self.main.addLayout(QtWidgets.QVBoxLayout())     # contextual boxes
        dialog = QtWidgets.QVBoxLayout()
        dialog.addWidget(QtWidgets.QScrollArea())        # the watchers
        self.main.addLayout(dialog, 1)
        self.addWidget(page)


class TasksInspectorTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tasks: Any = Tasks()
        self.bridges: list[Bridge] = []

        def make(parent: Any) -> Any:
            view = QtWidgets.QLabel("inspector", parent)
            view.nxt_bridge = Bridge()   # type: ignore[attr-defined]
            self.bridges.append(view.nxt_bridge)
            return view

        saved = (host.make_inspector, task_layout.task_view,
                 task_layout.Keyboard, task_layout.Repaint)
        host.make_inspector = make  # type: ignore[assignment]
        task_layout.task_view = lambda: self.tasks  # type: ignore
        task_layout.Keyboard = task_layout.Repaint = (  # type: ignore
            lambda view: None)
        self.addCleanup(self.restore, saved)
        self.part = tasks_inspector.TasksInspector()
        self.addCleanup(self.part.remove)

    def restore(self, saved: tuple[Any, ...]) -> None:
        (host.make_inspector, task_layout.task_view,
         task_layout.Keyboard, task_layout.Repaint) = saved

    def stretches(self) -> list[int]:
        return [self.tasks.main.stretch(i)
                for i in range(self.tasks.main.count())]

    def test_it_goes_below_the_boxes_and_takes_the_rest(self) -> None:
        self.part.install()
        main = self.tasks.main
        self.assertEqual(main.count(), 3)
        self.assertIs(main.itemAt(2).widget(), self.part._view)
        self.assertEqual(self.stretches(), [0, 0, 1])

    def test_a_dialog_page_stops_the_polling(self) -> None:
        self.part.install()
        bridge = self.bridges[0]
        self.assertTrue(bridge.running)
        self.tasks.addWidget(QtWidgets.QWidget())
        self.tasks.setCurrentIndex(1)
        self.assertFalse(bridge.running)
        self.tasks.setCurrentIndex(0)
        self.assertTrue(bridge.running)

    def test_it_takes_no_room_with_nothing_selected(self) -> None:
        self.part.install()
        bridge = self.bridges[0]
        self.assertTrue(self.part._view.isHidden())
        bridge.title = "Pad"
        bridge.changed.emit()
        self.assertFalse(self.part._view.isHidden())
        bridge.title = ""
        bridge.changed.emit()
        self.assertTrue(self.part._view.isHidden())

    def test_remove_leaves_the_layout_as_found(self) -> None:
        self.part.install()
        self.part.remove()
        APP.processEvents()
        self.assertEqual(self.tasks.main.count(), 2)
        self.assertEqual(self.stretches(), [0, 1])
        self.assertFalse(self.bridges[0].running)
        self.assertFalse(self.part._find.isActive())

    def test_a_new_task_view_is_found_again(self) -> None:
        self.part.install()
        shiboken6.delete(self.tasks)
        self.tasks = Tasks()
        self.part._watch()
        self.assertEqual(len(self.bridges), 2)
        self.assertIs(self.tasks.main.itemAt(2).widget(), self.part._view)

    def test_nothing_to_find_is_not_an_error(self) -> None:
        self.tasks = None
        self.part.install()
        self.assertIsNone(self.part._view)


if __name__ == "__main__":
    unittest.main(verbosity=2)

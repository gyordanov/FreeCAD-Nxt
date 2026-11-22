"""The inspector in the Tasks panel, on both of FreeCAD's stack layouts.

Run with: python3 tests/test_tasks_inspector.py
"""

from __future__ import annotations

import os
import sys
import types
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
    """FreeCAD's task view; every panel is the boxes above a dialog area."""

    taskUpdate = QtCore.Signal()  # noqa: N815 - FreeCAD's name

    def panel(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        main = QtWidgets.QVBoxLayout(page)
        main.addLayout(QtWidgets.QVBoxLayout())          # contextual boxes
        dialog = QtWidgets.QVBoxLayout()
        dialog.addWidget(QtWidgets.QScrollArea())        # the watchers
        main.addLayout(dialog, 1)
        self.addWidget(page)
        return page


def stretches(page: Any) -> list[int]:
    main = page.layout()
    return [main.stretch(i) for i in range(main.count())]


class _Base(unittest.TestCase):

    def setUp(self) -> None:
        self.tasks = Tasks()
        self.dialog = False
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
        Gui.Control = types.SimpleNamespace(  # type: ignore[attr-defined]
            activeDialog=lambda: self.dialog)
        self.addCleanup(delattr, Gui, "Control")
        self.addCleanup(self.restore, saved)
        self.part = tasks_inspector.TasksInspector()
        self.addCleanup(self.part.remove)

    def restore(self, saved: tuple[Any, ...]) -> None:
        (host.make_inspector, task_layout.task_view,
         task_layout.Keyboard, task_layout.Repaint) = saved

    def select(self, title: str = "Pad") -> None:
        self.bridges[-1].title = title
        self.bridges[-1].changed.emit()

    def last(self, page: Any) -> Any:
        main = page.layout()
        return main.itemAt(main.count() - 1).widget()


class PerDocumentPageTests(_Base):
    """Newer FreeCAD: a page per document, a dialog sharing its page."""

    def setUp(self) -> None:
        super().setUp()
        self.first = self.tasks.panel()
        self.part.install()

    def test_it_goes_below_the_boxes_and_takes_the_rest(self) -> None:
        self.assertIs(self.last(self.first), self.part._view)
        self.assertEqual(stretches(self.first), [0, 0, 1])
        self.assertTrue(self.bridges[0].running)

    def test_it_takes_no_room_with_nothing_selected(self) -> None:
        self.assertTrue(self.part._view.isHidden())
        self.select()
        self.assertFalse(self.part._view.isHidden())
        self.select("")
        self.assertTrue(self.part._view.isHidden())

    def test_a_dialog_on_the_same_page_hides_it_and_gives_room_back(
            self) -> None:
        self.select()
        self.dialog = True
        self.tasks.taskUpdate.emit()
        self.assertTrue(self.part._view.isHidden())
        self.assertFalse(self.bridges[0].running)
        self.assertEqual(stretches(self.first), [0, 1])
        self.assertEqual(self.first.layout().count(), 2)
        self.dialog = False
        self.tasks.taskUpdate.emit()
        self.assertFalse(self.part._view.isHidden())
        self.assertTrue(self.bridges[0].running)
        self.assertEqual(stretches(self.first), [0, 0, 1])

    def test_the_tick_notices_a_dialog_with_no_signal(self) -> None:
        self.select()
        self.dialog = True
        self.part._tick.timeout.emit()
        self.assertFalse(self.bridges[0].running)
        self.assertTrue(self.part._view.isHidden())

    def test_a_document_switch_moves_it_with_each_page_as_found(
            self) -> None:
        second = self.tasks.panel()
        self.tasks.setCurrentWidget(second)
        self.assertIs(self.last(second), self.part._view)
        self.assertEqual(stretches(second), [0, 0, 1])
        self.assertEqual(self.first.layout().count(), 2)
        self.assertEqual(stretches(self.first), [0, 1])
        self.assertEqual(len(self.bridges), 1)

    def test_a_deleted_page_does_not_take_it_along(self) -> None:
        second = self.tasks.panel()
        self.tasks.removeWidget(self.first)     # FreeCAD, then deletes it
        shiboken6.delete(self.first)
        self.assertTrue(shiboken6.isValid(self.part._view))
        self.assertIs(self.last(second), self.part._view)
        self.assertEqual(len(self.bridges), 1)

    def test_a_page_deleted_unannounced_is_rebuilt_on_the_tick(self) -> None:
        second = self.tasks.panel()
        shiboken6.delete(self.first)
        self.part._tick.timeout.emit()
        self.assertEqual(len(self.bridges), 2)
        self.assertIs(self.last(second), self.part._view)
        self.assertTrue(self.bridges[1].running)

    def test_remove_leaves_every_page_as_found(self) -> None:
        second = self.tasks.panel()
        self.tasks.setCurrentWidget(second)
        self.dialog = True
        self.tasks.taskUpdate.emit()
        self.dialog = False
        self.tasks.setCurrentWidget(self.first)
        self.part.remove()
        APP.processEvents()
        for page in (self.first, second):
            self.assertEqual(page.layout().count(), 2)
            self.assertEqual(stretches(page), [0, 1])
        self.assertFalse(any(b.running for b in self.bridges))
        self.assertFalse(self.part._tick.isActive())


class IdlePageTests(_Base):
    """Older FreeCAD: page 0 is idle, a dialog gets a page of its own."""

    def setUp(self) -> None:
        super().setUp()
        self.idle = self.tasks.panel()
        self.part.install()
        self.select()

    def test_a_dialog_page_hides_it_and_closing_brings_it_back(self) -> None:
        dialog = self.tasks.panel()
        self.dialog = True
        self.tasks.setCurrentWidget(dialog)
        self.assertTrue(self.part._view.isHidden())
        self.assertFalse(self.bridges[0].running)
        self.assertEqual(stretches(self.idle), [0, 1])
        self.assertEqual(dialog.layout().count(), 2)
        self.dialog = False
        self.tasks.removeWidget(dialog)
        shiboken6.delete(dialog)
        self.assertIs(self.last(self.idle), self.part._view)
        self.assertFalse(self.part._view.isHidden())
        self.assertTrue(self.bridges[0].running)
        self.assertEqual(stretches(self.idle), [0, 0, 1])
        self.assertEqual(len(self.bridges), 1)

    def test_nothing_to_find_is_not_an_error(self) -> None:
        self.part.remove()
        self.tasks = None   # type: ignore[assignment]
        part = tasks_inspector.TasksInspector()
        part.install()
        part.remove()
        self.assertIsNone(part._view)


if __name__ == "__main__":
    unittest.main(verbosity=2)

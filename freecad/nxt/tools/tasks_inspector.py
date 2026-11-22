"""The Property Inspector in FreeCAD's Tasks panel (`InspectorInTasks`).

FreeCAD's task view is a stack: page 0 is the idle panel, where the
workbench's boxes are shown, and each task dialog gets a page of its own.
The inspector is added to page 0, under those boxes, so a dialog covers it
and closing the dialog brings it back. It is never given to
`addTaskWatcher`, which would delete the workbench's boxes.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ..core import widgets
from ..core.qt import QtCore, QtWidgets
from ..inspector import host
from . import task_layout

#: FreeCAD's task panel exists from startup, but is looked for until found.
FIND_MS = 500
MIN_HEIGHT = 160


class TasksInspector(QtCore.QObject):
    """Keeps the inspector in the idle page of whichever task view lives."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: Any = None
        self._layout: Any = None
        self._view: Any = None
        self._bridge: Any = None
        #: The layout's stretch per item before the inspector took the rest.
        self._stretch: list[tuple[int, int]] = []
        self._find = QtCore.QTimer(self)
        self._find.setInterval(FIND_MS)
        self._find.timeout.connect(self._watch)

    def install(self) -> None:
        self._find.start()
        self._watch()

    def remove(self) -> None:
        self._find.stop()
        self._detach()

    def _watch(self) -> None:
        if widgets.alive(self._tasks) and widgets.alive(self._view):
            return
        self._detach()
        tasks = task_layout.task_view()
        if tasks is not None:
            self._attach(tasks)

    def _attach(self, tasks: Any) -> None:
        page = tasks.widget(0)
        layout = page.layout() if page is not None else None
        if not isinstance(layout, QtWidgets.QBoxLayout):
            return
        view = host.make_inspector(page)
        view.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        view.setMinimumHeight(MIN_HEIGHT)
        view.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        keys, paint = task_layout.Keyboard(view), task_layout.Repaint(view)
        view.nxt_keys = keys  # type: ignore[attr-defined]
        view.nxt_paint = paint  # type: ignore[attr-defined]
        self._tasks, self._layout, self._view = tasks, layout, view
        self._bridge = view.nxt_bridge
        # The boxes keep their own height; the inspector takes the rest.
        self._stretch = [(i, layout.stretch(i)) for i in range(layout.count())]
        for index, _ in self._stretch:
            layout.setStretch(index, 0)
        layout.addWidget(view, 1)
        self._bridge.changed.connect(self._sync_empty)
        tasks.currentChanged.connect(self._page_changed)
        self._page_changed(tasks.currentIndex())
        self._sync_empty()

    def _detach(self) -> None:
        view, bridge, tasks = self._view, self._bridge, self._tasks
        self._view = self._bridge = self._tasks = None
        if bridge is not None and widgets.alive(bridge):
            bridge.stop()
        if widgets.alive(tasks):
            with contextlib.suppress(RuntimeError, TypeError):
                tasks.currentChanged.disconnect(self._page_changed)
        if widgets.alive(view):
            view.hide()
            if widgets.alive(self._layout):
                self._layout.removeWidget(view)
                for index, stretch in self._stretch:
                    self._layout.setStretch(index, stretch)
            view.setParent(None)
            view.deleteLater()
        self._layout = None
        self._stretch = []

    def _page_changed(self, index: int) -> None:
        """Poll only while idle: a dialog's feature is its own to edit."""
        if self._bridge is None:
            return
        if index == 0:
            self._bridge.start()
        else:
            self._bridge.stop()

    def _sync_empty(self) -> None:
        """Nothing selected: no room is taken."""
        if widgets.alive(self._view):
            self._view.setVisible(bool(self._bridge.title))

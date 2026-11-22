"""The Property Inspector in FreeCAD's Tasks panel (`InspectorInTasks`).

FreeCAD's task view is a stack of panels: one per document in newer
builds, a dialog sharing its document's panel; in older ones an idle panel
on page 0 and a page per dialog. Either way the one inspector view sits
at the bottom of the panel on show while no dialog is active, and is
hidden and idle while one is, so it never edits under a dialog. It is
never given to `addTaskWatcher`, which would delete the workbench's boxes.
"""

from __future__ import annotations

import contextlib
from typing import Any

import FreeCADGui as Gui

from ..core import log, widgets
from ..core.qt import QtCore, QtWidgets
from ..inspector import host
from . import task_layout

#: The safety net: a dialog opening or closing is noticed within a tick,
#: whether or not FreeCAD's signals say so.
FIND_MS = 500
MIN_HEIGHT = 160


#: The task view's signals that mean what is shown may have changed;
#: older builds may lack `taskUpdate`.
_SIGNALS = (("currentChanged", "_evaluate"), ("widgetRemoved", "_rescue"),
            ("taskUpdate", "_evaluate"))


def _dialog_open() -> bool:
    try:
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


class TasksInspector(QtCore.QObject):
    """Keeps the inspector in whichever task panel is shown."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: Any = None
        self._view: Any = None
        self._bridge: Any = None
        self._failed = False
        self._polling = False
        #: The layout the view is in, and what its other items' stretch
        #: was before they gave way (None while restored).
        self._layout: Any = None
        self._stretch: list[tuple[int, int]] | None = None
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(FIND_MS)
        self._tick.timeout.connect(self._evaluate)

    def install(self) -> None:
        self._tick.start()
        self._evaluate()

    def remove(self) -> None:
        self._tick.stop()
        self._unwatch()
        self._park()
        view = self._view
        self._view = self._bridge = None
        if widgets.alive(view):
            view.setParent(None)
            view.deleteLater()

    # -- the task view -- #

    def _unwatch(self) -> None:
        tasks = self._tasks
        self._tasks = None
        if not widgets.alive(tasks):
            return
        for name, slot in _SIGNALS:
            signal = getattr(tasks, name, None)
            if signal is not None:
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(getattr(self, slot))

    def _watch(self) -> bool:
        if widgets.alive(self._tasks):
            return True
        self._unwatch()
        tasks = task_layout.task_view()
        if tasks is None:
            return False
        self._tasks = tasks
        for name, slot in _SIGNALS:
            signal = getattr(tasks, name, None)
            if signal is not None:
                signal.connect(getattr(self, slot))
        return True

    def _rescue(self, *_args: Any) -> None:
        """A panel is about to be deleted: take the view out of it."""
        view, tasks = self._view, self._tasks
        if not widgets.alive(view) or not widgets.alive(tasks):
            return
        if tasks.indexOf(view.parentWidget()) < 0:
            self._park()
            view.setParent(None)

    # -- the view -- #

    def _build(self) -> bool:
        if self._failed:
            return False
        try:
            view = host.make_inspector(self._tasks.currentWidget())
        except Exception:
            self._failed = True
            log.error("could not make the inspector for the Tasks panel")
            return False
        view.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        view.setMinimumHeight(MIN_HEIGHT)
        view.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        keys, paint = task_layout.Keyboard(view), task_layout.Repaint(view)
        view.nxt_keys = keys  # type: ignore[attr-defined]
        view.nxt_paint = paint  # type: ignore[attr-defined]
        self._view = view
        self._bridge = view.nxt_bridge
        self._bridge.changed.connect(self._sync_empty)
        self._polling = False
        self._layout = None
        self._stretch = None
        return True

    def _evaluate(self, *_args: Any) -> None:
        if not self._watch():
            return
        if not widgets.alive(self._view):
            self._view = self._bridge = None
            self._layout = None
            self._stretch = None
            if not self._build():
                return
        if _dialog_open():
            self._park()
        else:
            self._place()

    def _park(self) -> None:
        """Hidden, idle and out of the layout: the page is as it was."""
        if self._bridge is not None and self._polling:
            self._polling = False
            if widgets.alive(self._bridge):
                self._bridge.stop()
        if widgets.alive(self._view):
            self._view.hide()
        self._leave()

    def _place(self) -> None:
        page = self._tasks.currentWidget()
        layout = page.layout() if page is not None else None
        if not isinstance(layout, QtWidgets.QBoxLayout):
            return
        if layout is not self._layout or layout.indexOf(self._view) < 0:
            self._leave()
            self._view.setParent(page)
            self._layout = layout
            layout.addWidget(self._view, 1)
        if self._stretch is None:
            self._squeeze(layout)
        if not self._polling:
            self._polling = True
            self._bridge.start()
        self._sync_empty()

    def _squeeze(self, layout: Any) -> None:
        """The page's own items keep their height; the view takes the rest."""
        here = layout.indexOf(self._view)
        self._stretch = [(i, layout.stretch(i)) for i in range(layout.count())
                         if i != here]
        for index, _stretch in self._stretch:
            layout.setStretch(index, 0)

    def _unsqueeze(self) -> None:
        layout, saved = self._layout, self._stretch
        self._stretch = None
        if saved is not None and widgets.alive(layout):
            for index, stretch in saved:
                layout.setStretch(index, stretch)

    def _leave(self) -> None:
        """Out of its layout, which is left as found."""
        self._unsqueeze()
        layout = self._layout
        self._layout = None
        if widgets.alive(layout) and widgets.alive(self._view):
            layout.removeWidget(self._view)

    def _sync_empty(self) -> None:
        """Nothing selected, or a dialog up: no room is taken."""
        if widgets.alive(self._view) and self._polling:
            self._view.setVisible(bool(self._bridge.title))

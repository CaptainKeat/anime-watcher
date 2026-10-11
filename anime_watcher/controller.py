"""Window-scoped XInput navigation. Never inject input into other applications."""
from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QLineEdit, QScrollArea, QSlider, QSpinBox, QTabWidget, QWidget


@dataclass(frozen=True)
class PadState:
    buttons: int = 0
    x: int = 0
    y: int = 0


class PadActions:
    BUTTONS = {0x1000:'accept', 0x2000:'back', 0x4000:'play_pause', 0x8000:'settings',
               0x0100:'previous_tab', 0x0200:'next_tab', 0x0010:'fullscreen'}
    def __init__(self): self.previous=0; self.direction=None; self.repeat_at=0; self.armed=True

    def reset(self): self.previous=0; self.direction=None; self.armed=False

    def actions(self, state, now):
        if not self.armed:
            if state.buttons == 0 and abs(state.x) < 9000 and abs(state.y) < 9000: self.armed=True
            return []
        pressed=state.buttons & ~self.previous; self.previous=state.buttons
        result=[action for bit,action in self.BUTTONS.items() if pressed & bit]
        direction = ('up' if state.buttons & 1 else 'down' if state.buttons & 2 else 'left' if state.buttons & 4 else 'right' if state.buttons & 8 else
                     ('right' if state.x>0 else 'left') if abs(state.x)>12000 and abs(state.x)>abs(state.y) else
                     ('up' if state.y>0 else 'down') if abs(state.y)>12000 else None)
        if direction:
            if direction != self.direction: result.append(direction); self.repeat_at=now+.4
            elif now >= self.repeat_at: result.append(direction); self.repeat_at=now+.14
        self.direction=direction
        return result


class XInput:
    def __init__(self):
        self.function=None
        if os.name != 'nt': return
        class Gamepad(ctypes.Structure):
            _fields_=[('buttons',ctypes.c_uint16),('lt',ctypes.c_uint8),('rt',ctypes.c_uint8),('x',ctypes.c_int16),('y',ctypes.c_int16),('rx',ctypes.c_int16),('ry',ctypes.c_int16)]
        class State(ctypes.Structure): _fields_=[('packet',ctypes.c_uint32),('pad',Gamepad)]
        self.state_type=State
        for name in ('xinput1_4.dll','xinput9_1_0.dll'):
            try:
                dll=ctypes.WinDLL(str(Path(os.environ['SystemRoot'])/'System32'/name))
                function=dll.XInputGetState; function.argtypes=[ctypes.c_uint32,ctypes.POINTER(State)]; function.restype=ctypes.c_uint32
                self.function=function; self.dll=dll; break
            except (OSError,KeyError,AttributeError): pass

    def read(self):
        if self.function is None: return None
        for index in range(4):
            state=self.state_type()
            if self.function(index,ctypes.byref(state)) == 0: return PadState(state.pad.buttons,state.pad.x,state.pad.y)
        return None


class ControllerNavigation(QObject):
    def __init__(self, window, reader=None):
        super().__init__(window); self.window=window; self.reader=reader or XInput(); self.mapper=PadActions(); self.connected=False
        self.timer=QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.tick); self.timer.start()

    def tick(self):
        state=self.reader.read(); self.connected=state is not None
        owner=QApplication.activeModalWidget() or QApplication.activeWindow()
        if not state or owner is None or (owner is not self.window and not self.window.isAncestorOf(owner)) or not self.window.db.setting('controller_enabled',True):
            self.mapper.reset(); return
        for action in self.mapper.actions(state,time.monotonic()): self.dispatch(action,owner)

    def dispatch(self, action, owner=None):
        owner=owner or self.window; focus=QApplication.focusWidget()
        if action in {'up','down','left','right'}:
            if isinstance(focus,(QComboBox,QSlider,QAbstractSpinBox,QLineEdit,QAbstractItemView)):
                keys={'up':Qt.Key.Key_Up,'down':Qt.Key.Key_Down,'left':Qt.Key.Key_Left,'right':Qt.Key.Key_Right}
                self._key(focus,keys[action]); return
            self.move(action,owner); return
        if action in {'next_tab','previous_tab'}:
            tabs=next((item for item in owner.findChildren(QTabWidget) if item.isVisibleTo(owner)),None)
            if tabs: tabs.setCurrentIndex((tabs.currentIndex()+(1 if action=='next_tab' else -1))%tabs.count())
            return
        if action == 'back':
            if owner is not self.window:
                if hasattr(owner,'reject'): owner.reject()
                else: self._key(owner,Qt.Key.Key_Escape)
                return
            window=self.window
            if window.current_episode_id:
                if window.player_settings.isVisible(): window._toggle_player_settings(False); return
                episode=window.db.episode(window.current_episode_id)
                if episode: window.show_series(episode['series_id'])
            elif window.visible_series_id: window.show_library()
            else: window.show_home()
            return
        if owner is self.window and self.window.current_episode_id:
            if action in {'play_pause','accept'} and (focus is None or not focus.isVisible()): self.window._toggle_play(); return
            if action=='play_pause': self.window._toggle_play(); return
            if action=='settings': self.window._toggle_player_settings(not self.window.player_settings.isVisible()); return
            if action=='fullscreen': self.window._toggle_fullscreen(); return
        if action=='accept' and focus is not None and owner.isAncestorOf(focus):
            if isinstance(focus,QAbstractButton): focus.click()
            elif isinstance(focus,QComboBox): focus.showPopup()
            elif hasattr(focus,'clicked'): focus.clicked.emit()
            else: self._key(focus,Qt.Key.Key_Return)

    @staticmethod
    def _key(target,key):
        for kind in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease): QApplication.sendEvent(target,QKeyEvent(kind,key,Qt.KeyboardModifier.NoModifier))

    def move(self,direction,owner):
        candidates=[widget for widget in owner.findChildren(QWidget) if widget.isVisibleTo(owner) and widget.isEnabled() and widget.focusPolicy()!=Qt.FocusPolicy.NoFocus
                    and (isinstance(widget,(QAbstractButton,QComboBox,QLineEdit,QSlider,QSpinBox)) or hasattr(widget,'clicked'))]
        if not candidates: return
        focus=QApplication.focusWidget()
        if focus not in candidates: chosen=candidates[0]
        else:
            origin=focus.mapTo(owner,focus.rect().center()); choices=[]
            for widget in candidates:
                if widget is focus: continue
                point=widget.mapTo(owner,widget.rect().center()); dx,dy=point.x()-origin.x(),point.y()-origin.y()
                forward=dx if direction=='right' else -dx if direction=='left' else dy if direction=='down' else -dy
                across=abs(dy) if direction in {'left','right'} else abs(dx)
                if forward>0: choices.append((forward+across*3,across,widget))
            if not choices: return
            chosen=min(choices,key=lambda row:row[:2])[2]
        chosen.setFocus(Qt.FocusReason.OtherFocusReason)
        parent=chosen.parentWidget()
        while parent and parent is not owner:
            if isinstance(parent,QScrollArea): parent.ensureWidgetVisible(chosen,24,24); break
            parent=parent.parentWidget()

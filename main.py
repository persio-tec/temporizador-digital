#!/usr/sbin/python3
"""Temporizador digital para Linux com autosalvamento e desligamento opcional."""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, QProcess, QTimer, Qt, QUrl
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
APP_NAME = "Temporizador Digital"
STATE_DIRECTORY = Path.home() / ".local" / "share" / "temporizador-digital"
STATE_FILE = STATE_DIRECTORY / "estado.json"
SOUND_FILE = STATE_DIRECTORY / "alarme.wav"
ICON_FILE = Path(__file__).resolve().with_name("temporizador-digital.svg")
SHUTDOWN_GRACE_SECONDS = 60
SHUTDOWN_SECONDS = 60


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def make_alarm_sound(path: Path) -> None:
    import struct
    import wave

    sample_rate = 24_000
    duration = 1.5
    samples = bytearray()
    for index in range(int(sample_rate * duration)):
        sample_time = index / sample_rate
        envelope = min(1.0, sample_time * 25) * min(1.0, (duration - sample_time) * 12)
        frequency = 880 if int(sample_time * 4) % 2 == 0 else 660
        value = int(11_000 * envelope * math.sin(2 * math.pi * frequency * sample_time))
        samples.extend(struct.pack("<h", value))

    with wave.open(str(path), "wb") as sound_file:
        sound_file.setnchannels(1)
        sound_file.setsampwidth(2)
        sound_file.setframerate(sample_rate)
        sound_file.writeframes(samples)


class TimerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.app_icon = QIcon(str(ICON_FILE))
        self.setWindowIcon(self.app_icon)
        self.setMinimumSize(760, 700)
        self.resize(900, 820)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#central { background: #10151e; color: #e8edf5; }
            QFrame#panel { background: #19212d; border: 1px solid #293547; border-radius: 14px; }
            QLabel#eyebrow { color: #9aabc0; font-size: 12px; font-weight: 600; }
            QLabel#clock { color: #93a4ff; font-size: 35px; font-weight: 600; }
            QLabel#timer { color: #ffffff; font-size: 67px; font-weight: 600; }
            QLabel#status { color: #bdc9d8; font-size: 13px; }
            QLabel#hint { color: #9aabc0; font-size: 12px; }
            QSpinBox, QPlainTextEdit {
                background: #10151e; color: #e8edf5; border: 1px solid #344258;
                border-radius: 7px; padding: 8px;
            }
            QSpinBox { min-width: 70px; font-size: 16px; }
            QCheckBox { spacing: 9px; }
            QPushButton {
                background: #293547; color: #f3f6fb; border: 0; border-radius: 8px;
                padding: 10px 16px; font-weight: 600;
            }
            QPushButton:hover { background: #37475d; }
            QPushButton#primary { background: #7186ff; color: #10151e; }
            QPushButton#primary:hover { background: #8a9aff; }
            QPushButton#danger { background: #773b43; }
            QPushButton#danger:hover { background: #914b54; }
            """
        )

        self.deadline: float | None = None
        self.paused_seconds: int | None = None
        self.shutdown_deadline: float | None = None
        self.shutdown_process: QProcess | None = None
        self.shutdown_error_reported = False
        self.storage_error_shown = False
        self.last_saved_clock_second = -1
        self.last_countdown_autosave_second = -1
        self.sound = QSoundEffect(self)
        self.sound.setLoopCount(2)
        self.sound.setVolume(0.75)

        self._build_interface()
        self._build_system_tray()
        self._load_state()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(250)

        self.task_save_timer = QTimer(self)
        self.task_save_timer.setSingleShot(True)
        self.task_save_timer.setInterval(500)
        self.task_save_timer.timeout.connect(self._save_state)
        self.tasks_edit.textChanged.connect(self.task_save_timer.start)
        self.shutdown_checkbox.toggled.connect(self._save_state)
        self.alarm_checkbox.toggled.connect(self._save_state)
        self._tick()

    def _build_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()

        open_action = QAction("Abrir temporizador", self)
        open_action.triggered.connect(self._show_window)
        menu.addAction(open_action)
        menu.addSeparator()

        self.tray_timer_action = QAction("Iniciar temporizador", self)
        self.tray_timer_action.triggered.connect(self._toggle_timer_from_tray)
        menu.addAction(self.tray_timer_action)

        reset_action = QAction("Zerar temporizador", self)
        reset_action.triggered.connect(self._reset)
        menu.addAction(reset_action)

        menu.addSeparator()
        quit_action = QAction("Sair do aplicativo", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

        menu.aboutToShow.connect(self._update_tray_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_timer_from_tray(self) -> None:
        if self.deadline is not None:
            self._pause()
        else:
            self._start_or_resume()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _update_tray_menu(self) -> None:
        if self.deadline is not None:
            self.tray_timer_action.setText("Pausar temporizador")
        elif self.paused_seconds is not None:
            self.tray_timer_action.setText("Retomar temporizador")
        else:
            self.tray_timer_action.setText("Iniciar temporizador")

    def _build_interface(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 24, 30, 25)
        layout.setSpacing(17)

        top_row = QHBoxLayout()
        title = QLabel("TEMPORIZADOR DIGITAL")
        title.setObjectName("eyebrow")
        top_row.addWidget(title)
        top_row.addStretch()
        minimize_button = QPushButton("Minimizar")
        minimize_button.clicked.connect(self.showMinimized)
        maximize_button = QPushButton("Maximizar")
        self.maximize_button = maximize_button
        maximize_button.clicked.connect(self._toggle_maximized)
        top_row.addWidget(minimize_button)
        top_row.addWidget(maximize_button)
        layout.addLayout(top_row)

        clock_panel = QFrame()
        clock_panel.setObjectName("panel")
        clock_layout = QVBoxLayout(clock_panel)
        clock_layout.setContentsMargins(22, 15, 22, 15)
        clock_layout.setSpacing(0)
        clock_caption = QLabel("HORA ATUAL")
        clock_caption.setObjectName("eyebrow")
        clock_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setObjectName("clock")
        self.clock_label.setFont(QFont("monospace", 35, QFont.Weight.DemiBold))
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_label = QLabel("")
        self.date_label.setObjectName("hint")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clock_layout.addWidget(clock_caption)
        clock_layout.addWidget(self.clock_label)
        clock_layout.addWidget(self.date_label)
        layout.addWidget(clock_panel)

        timer_panel = QFrame()
        timer_panel.setObjectName("panel")
        timer_layout = QVBoxLayout(timer_panel)
        timer_layout.setContentsMargins(22, 15, 22, 17)
        timer_layout.setSpacing(9)
        timer_caption = QLabel("TEMPO RESTANTE")
        timer_caption.setObjectName("eyebrow")
        timer_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label = QLabel("00:25:00")
        self.timer_label.setObjectName("timer")
        self.timer_label.setFont(QFont("monospace", 67, QFont.Weight.DemiBold))
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(timer_caption)
        timer_layout.addWidget(self.timer_label)

        duration_row = QHBoxLayout()
        duration_row.addStretch()
        for label, attribute, maximum in (
            ("Horas", "hours_input", 99),
            ("Minutos", "minutes_input", 59),
            ("Segundos", "seconds_input", 59),
        ):
            group = QVBoxLayout()
            field_label = QLabel(label)
            field_label.setObjectName("hint")
            field_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field = QSpinBox()
            field.setRange(0, maximum)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setButtonSymbols(QSpinBox.ButtonSymbols.PlusMinus)
            setattr(self, attribute, field)
            group.addWidget(field_label)
            group.addWidget(field)
            duration_row.addLayout(group)
        self.minutes_input.setValue(25)
        duration_row.addStretch()
        timer_layout.addLayout(duration_row)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Iniciar")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_or_resume)
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self._pause)
        reset_button = QPushButton("Zerar")
        reset_button.clicked.connect(self._reset)
        button_row.addStretch()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.pause_button)
        button_row.addWidget(reset_button)
        button_row.addStretch()
        timer_layout.addLayout(button_row)
        layout.addWidget(timer_panel)

        self.status_label = QLabel("Defina a duração e inicie o temporizador.")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        options_row = QHBoxLayout()
        self.alarm_checkbox = QCheckBox("Tocar som ao terminar")
        self.alarm_checkbox.setChecked(True)
        self.shutdown_checkbox = QCheckBox("Desligar o computador ao terminar")
        self.shutdown_checkbox.setObjectName("shutdown")
        options_row.addWidget(self.alarm_checkbox)
        options_row.addStretch()
        options_row.addWidget(self.shutdown_checkbox)
        layout.addLayout(options_row)

        shutdown_hint = QLabel(
            "O desligamento aguarda 60 segundos e pode ser cancelado. "
            "No KDE, os aplicativos podem pedir que você salve arquivos antes de fechar."
        )
        shutdown_hint.setObjectName("hint")
        shutdown_hint.setWordWrap(True)
        layout.addWidget(shutdown_hint)

        self.cancel_shutdown_button = QPushButton("Cancelar desligamento")
        self.cancel_shutdown_button.setObjectName("danger")
        self.cancel_shutdown_button.clicked.connect(self._cancel_shutdown)
        self.cancel_shutdown_button.hide()
        layout.addWidget(self.cancel_shutdown_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        tasks_title = QLabel("Tarefas em aberto")
        tasks_title.setObjectName("eyebrow")
        layout.addWidget(tasks_title)
        self.tasks_edit = QPlainTextEdit()
        self.tasks_edit.setPlaceholderText("Anote suas tarefas; elas são salvas automaticamente.")
        layout.addWidget(self.tasks_edit, stretch=1)
        self.save_label = QLabel("As tarefas são salvas automaticamente neste computador.")
        self.save_label.setObjectName("hint")
        layout.addWidget(self.save_label)

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("Maximizar")
        else:
            self.showMaximized()
            self.maximize_button.setText("Restaurar")

    def _load_state(self) -> None:
        STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(STATE_DIRECTORY, 0o700)
        except OSError:
            pass
        if not STATE_FILE.exists():
            make_alarm_sound(SOUND_FILE)
            self.sound.setSource(QUrl.fromLocalFile(str(SOUND_FILE)))
            self._save_state()
            return

        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            QMessageBox.critical(
                self,
                "Não foi possível carregar os dados",
                f"Os dados salvos não puderam ser lidos. O arquivo foi mantido intacto.\n\n{error}",
            )
            return

        if not isinstance(state, dict):
            raise RuntimeError(f"Formato inválido em {STATE_FILE}.")
        self.tasks_edit.setPlainText(str(state.get("tasks", "")))
        self.alarm_checkbox.setChecked(bool(state.get("alarm_enabled", True)))
        self.shutdown_checkbox.setChecked(bool(state.get("shutdown_enabled", False)))
        self.hours_input.setValue(int(state.get("hours", 0)))
        self.minutes_input.setValue(int(state.get("minutes", 25)))
        self.seconds_input.setValue(int(state.get("seconds", 0)))

        self.deadline = self._optional_number(state.get("deadline"))
        self.paused_seconds = self._optional_integer(state.get("paused_seconds"))
        self.shutdown_deadline = self._optional_number(state.get("shutdown_deadline"))

        if not SOUND_FILE.exists():
            make_alarm_sound(SOUND_FILE)
        self.sound.setSource(QUrl.fromLocalFile(str(SOUND_FILE)))

        if self.deadline is not None and self.deadline <= time.time():
            self.deadline = None
            self.paused_seconds = None
            self.shutdown_deadline = None
            self.status_label.setText(
                "O temporizador venceu enquanto o aplicativo estava fechado; confira antes de iniciar outro."
            )
            QTimer.singleShot(
                0,
                lambda: QMessageBox.information(
                    self,
                    "Temporizador vencido",
                    "O temporizador terminou enquanto o aplicativo estava fechado. "
                    "O desligamento automático foi cancelado por segurança.",
                ),
            )
        elif self.shutdown_deadline is not None:
            if self.shutdown_deadline <= time.time():
                self.shutdown_deadline = None
                self.status_label.setText(
                    "O desligamento pendente foi cancelado porque o aplicativo ficou fechado durante a contagem."
                )
            else:
                self.timer_label.setText("00:00:00")
                self.cancel_shutdown_button.show()

        if self.deadline is not None:
            self.start_button.setText("Em andamento")
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.status_label.setText("Temporizador restaurado automaticamente.")
        elif self.paused_seconds is not None:
            self.timer_label.setText(format_duration(self.paused_seconds))
            self.start_button.setText("Retomar")
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.status_label.setText("Temporizador pausado, restaurado automaticamente.")
        else:
            self.pause_button.setEnabled(False)

        self._save_state()

    @staticmethod
    def _optional_number(value: object) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        return int(value) if isinstance(value, (int, float)) else None

    def _state(self) -> dict[str, object]:
        return {
            "tasks": self.tasks_edit.toPlainText(),
            "alarm_enabled": self.alarm_checkbox.isChecked(),
            "shutdown_enabled": self.shutdown_checkbox.isChecked(),
            "hours": self.hours_input.value(),
            "minutes": self.minutes_input.value(),
            "seconds": self.seconds_input.value(),
            "deadline": self.deadline,
            "paused_seconds": self.paused_seconds,
            "shutdown_deadline": self.shutdown_deadline,
        }

    def _save_state(self) -> None:
        try:
            STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
            temporary_file = STATE_FILE.with_suffix(".tmp")
            temporary_file.write_text(
                json.dumps(self._state(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_file, STATE_FILE)
            try:
                os.chmod(STATE_FILE, 0o600)
            except OSError:
                pass
        except OSError as error:
            self.save_label.setText(f"Falha ao salvar automaticamente: {error}")
            self.save_label.setStyleSheet("color: #ff9c9c")
            if not self.storage_error_shown:
                self.storage_error_shown = True
                QMessageBox.warning(
                    self,
                    "Falha no salvamento automático",
                    f"Não foi possível salvar o estado do temporizador:\n\n{error}",
                )
            return

        self.storage_error_shown = False
        self.save_label.setText("Tarefas e temporizador salvos automaticamente.")
        self.save_label.setStyleSheet("")

    def _duration_from_inputs(self) -> int:
        return (
            self.hours_input.value() * 3600
            + self.minutes_input.value() * 60
            + self.seconds_input.value()
        )

    def _start_or_resume(self) -> None:
        if self.paused_seconds is not None:
            self.deadline = time.time() + self.paused_seconds
            self.paused_seconds = None
        else:
            duration = self._duration_from_inputs()
            if duration <= 0:
                QMessageBox.information(
                    self,
                    "Duração inválida",
                    "Escolha uma duração de pelo menos um segundo.",
                )
                return
            self.deadline = time.time() + duration

        self.shutdown_deadline = None
        self.cancel_shutdown_button.hide()
        self.start_button.setText("Em andamento")
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.status_label.setText("Temporizador em andamento.")
        self._save_state()
        self._tick()

    def _pause(self) -> None:
        if self.deadline is None:
            return
        self.paused_seconds = max(0, math.ceil(self.deadline - time.time()))
        self.deadline = None
        self.start_button.setText("Retomar")
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.status_label.setText("Temporizador pausado.")
        self._save_state()
        self._tick()

    def _reset(self) -> None:
        self.deadline = None
        self.paused_seconds = None
        self.shutdown_deadline = None
        self.start_button.setText("Iniciar")
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.cancel_shutdown_button.hide()
        self.timer_label.setText(format_duration(self._duration_from_inputs()))
        self.status_label.setText("Temporizador zerado.")
        self._save_state()

    def _cancel_shutdown(self) -> None:
        self.shutdown_deadline = None
        self.cancel_shutdown_button.hide()
        self.status_label.setText("Desligamento automático cancelado.")
        self._save_state()

    def _tick(self) -> None:
        now = time.time()
        local_time = time.localtime(now)
        if local_time.tm_sec != self.last_saved_clock_second:
            self.last_saved_clock_second = local_time.tm_sec
            self.clock_label.setText(time.strftime("%H:%M:%S", local_time))
            brazilian_portuguese = QLocale(
                QLocale.Language.Portuguese, QLocale.Country.Brazil
            )
            current_datetime = QDateTime.fromSecsSinceEpoch(int(now))
            self.date_label.setText(
                brazilian_portuguese.toString(
                    current_datetime, "dddd, dd 'de' MMMM 'de' yyyy"
                )
            )
            if hasattr(self, "tray"):
                if self.deadline is not None:
                    tray_status = f"Restante: {format_duration(math.ceil(self.deadline - now))}"
                elif self.paused_seconds is not None:
                    tray_status = f"Pausado: {format_duration(self.paused_seconds)}"
                elif self.shutdown_deadline is not None:
                    tray_status = (
                        f"Desligamento em "
                        f"{format_duration(math.ceil(self.shutdown_deadline - now))}"
                    )
                else:
                    tray_status = "Pronto para iniciar"
                self.tray.setToolTip(f"{APP_NAME} — {tray_status}")

        if self.deadline is not None:
            remaining = max(0, math.ceil(self.deadline - now))
            self.timer_label.setText(format_duration(remaining))
            if remaining == 0:
                self._timer_finished()
            elif (
                local_time.tm_sec % 5 == 0
                and local_time.tm_sec != self.last_countdown_autosave_second
            ):
                self.last_countdown_autosave_second = local_time.tm_sec
                self._save_state()
        elif self.paused_seconds is None and self.shutdown_deadline is None:
            self.timer_label.setText(format_duration(self._duration_from_inputs()))

        if self.shutdown_deadline is not None:
            remaining = max(0, math.ceil(self.shutdown_deadline - now))
            self.status_label.setText(
                f"Desligamento em {format_duration(remaining)} — cancele abaixo se necessário."
            )
            if remaining == 0:
                self._request_shutdown()

    def _timer_finished(self) -> None:
        self.deadline = None
        self.paused_seconds = None
        self.start_button.setText("Iniciar")
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.timer_label.setText("00:00:00")
        if self.alarm_checkbox.isChecked():
            self.sound.play()

        if self.shutdown_checkbox.isChecked():
            self.shutdown_deadline = time.time() + SHUTDOWN_GRACE_SECONDS
            self.cancel_shutdown_button.show()
            self.status_label.setText(
                "Temporizador concluído; o computador será desligado em 01:00."
            )
        else:
            self.status_label.setText("Temporizador concluído.")
        self._save_state()

    def _request_shutdown(self) -> None:
        if self.shutdown_process is not None:
            return
        self.shutdown_error_reported = False
        self.shutdown_deadline = None
        self.cancel_shutdown_button.hide()
        self._save_state()

        if self._is_kde_session():
            self.status_label.setText("Solicitando ao KDE o encerramento dos aplicativos…")
            self._request_kde_shutdown()
            return

        self.status_label.setText("Solicitando o desligamento gracioso ao sistema…")
        self.shutdown_process = QProcess(self)
        self.shutdown_process.finished.connect(self._shutdown_finished)
        self.shutdown_process.errorOccurred.connect(self._shutdown_process_error)
        self.shutdown_process.start("systemctl", ["poweroff"])

    @staticmethod
    def _is_kde_session() -> bool:
        desktop_names = os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
        return os.environ.get("KDE_FULL_SESSION", "").lower() == "true" or any(
            "kde" in desktop_name.lower() for desktop_name in desktop_names
        )

    def _request_kde_shutdown(self) -> None:
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            self._show_shutdown_error(bus.lastError().message())
            return

        message = QDBusMessage.createMethodCall(
            "org.kde.Shutdown",
            "/Shutdown",
            "org.kde.Shutdown",
            "logoutAndShutdown",
        )
        reply = bus.call(message)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            error = reply.errorMessage()
            if not error:
                error = "O gerenciador do KDE retornou uma resposta inválida."
            self._show_shutdown_error(error)
            return

        self.status_label.setText(
            "O KDE está fechando os aplicativos antes de desligar o computador."
        )

    def _shutdown_process_error(self, error: QProcess.ProcessError) -> None:
        if error not in (
            QProcess.ProcessError.FailedToStart,
            QProcess.ProcessError.Crashed,
        ):
            return
        self._show_shutdown_error(self.shutdown_process.errorString())

    def _shutdown_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        process = self.shutdown_process
        self.shutdown_process = None
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self.status_label.setText("Desligamento solicitado ao sistema.")
            return

        error = ""
        if process is not None:
            error = bytes(process.readAllStandardError()).decode(errors="replace").strip()
            if not error:
                error = process.errorString()
        self._show_shutdown_error(error)

    def _show_shutdown_error(self, error: str) -> None:
        if self.shutdown_error_reported:
            return
        self.shutdown_error_reported = True
        self.shutdown_process = None
        self.shutdown_checkbox.setChecked(False)
        self.status_label.setText("O sistema não autorizou o desligamento.")
        QMessageBox.warning(
            self,
            "Não foi possível desligar",
            "O desligamento não foi autorizado pelo sistema. "
            "Verifique as permissões de energia da sessão.\n\n"
            f"{error or 'O comando de desligamento falhou.'}",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.task_save_timer.stop()
        self._save_state()
        event.accept()


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    window = TimerWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

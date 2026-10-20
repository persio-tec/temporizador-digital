import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtDBus import QDBusMessage
from PySide6.QtWidgets import QApplication

import main


class TimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_directory = main.STATE_DIRECTORY
        self.state_file = main.STATE_FILE
        self.sound_file = main.SOUND_FILE
        main.STATE_DIRECTORY = Path(self.temporary_directory.name)
        main.STATE_FILE = main.STATE_DIRECTORY / "estado.json"
        main.SOUND_FILE = main.STATE_DIRECTORY / "alarme.wav"
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.close()
            self.window.deleteLater()
        main.STATE_DIRECTORY = self.state_directory
        main.STATE_FILE = self.state_file
        main.SOUND_FILE = self.sound_file
        self.temporary_directory.cleanup()

    def test_formats_durations(self):
        self.assertEqual(main.format_duration(0), "00:00:00")
        self.assertEqual(main.format_duration(3_661), "01:01:01")
        self.assertEqual(main.format_duration(-1), "00:00:00")

    def test_alarm_is_a_valid_wav_file(self):
        main.make_alarm_sound(main.SOUND_FILE)

        with wave.open(str(main.SOUND_FILE), "rb") as sound_file:
            self.assertEqual(sound_file.getnchannels(), 1)
            self.assertEqual(sound_file.getsampwidth(), 2)
            self.assertEqual(sound_file.getframerate(), 24_000)
            self.assertGreater(sound_file.getnframes(), 0)

    def test_custom_icon_and_tray_timer_actions(self):
        self.window = main.TimerWindow()
        self.assertTrue(main.ICON_FILE.is_file())
        self.assertFalse(self.window.windowIcon().isNull())

        self.window.minutes_input.setValue(0)
        self.window.seconds_input.setValue(30)
        self.window._toggle_timer_from_tray()
        self.assertIsNotNone(self.window.deadline)

        self.window._toggle_timer_from_tray()
        self.assertIsNone(self.window.deadline)
        self.assertEqual(self.window.paused_seconds, 30)

    def test_tasks_and_paused_timer_are_restored(self):
        self.window = main.TimerWindow()
        self.window.tasks_edit.setPlainText("Revisar relatório\nEnviar e-mail")
        self.window.minutes_input.setValue(10)
        self.window.seconds_input.setValue(5)
        self.window._start_or_resume()
        self.window._pause()
        self.window._save_state()

        self.window.close()
        self.window.deleteLater()
        self.window = main.TimerWindow()

        self.assertEqual(
            self.window.tasks_edit.toPlainText(),
            "Revisar relatório\nEnviar e-mail",
        )
        self.assertGreaterEqual(self.window.paused_seconds, 604)
        self.assertFalse(self.window.shutdown_checkbox.isChecked())

    def test_shutdown_has_a_cancelable_grace_period(self):
        self.window = main.TimerWindow()
        self.window.alarm_checkbox.setChecked(False)
        self.window.shutdown_checkbox.setChecked(True)
        self.window.seconds_input.setValue(1)
        self.window._start_or_resume()
        self.window.deadline = 0
        self.window._tick()

        self.assertIsNotNone(self.window.shutdown_deadline)
        self.assertGreater(self.window.shutdown_deadline, 0)
        self.assertFalse(self.window.cancel_shutdown_button.isHidden())

        self.window._cancel_shutdown()
        self.assertIsNone(self.window.shutdown_deadline)
        self.assertTrue(self.window.cancel_shutdown_button.isHidden())

    def test_shutdown_uses_kde_session_manager(self):
        self.window = main.TimerWindow()
        bus = Mock()
        bus.isConnected.return_value = True
        reply = Mock()
        reply.type.return_value = QDBusMessage.MessageType.ReplyMessage
        bus.call.return_value = reply

        with (
            patch.dict(main.os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}),
            patch("main.QDBusConnection.sessionBus", return_value=bus),
            patch("main.QProcess") as process,
        ):
            self.window._request_shutdown()

        self.assertFalse(process.called)
        message = bus.call.call_args.args[0]
        self.assertEqual(message.service(), "org.kde.Shutdown")
        self.assertEqual(message.path(), "/Shutdown")
        self.assertEqual(message.interface(), "org.kde.Shutdown")
        self.assertEqual(message.member(), "logoutAndShutdown")
        self.assertIn("fechando os aplicativos", self.window.status_label.text())

    def test_kde_shutdown_errors_are_reported(self):
        self.window = main.TimerWindow()
        bus = Mock()
        bus.isConnected.return_value = True
        reply = Mock()
        reply.type.return_value = QDBusMessage.MessageType.ErrorMessage
        reply.errorMessage.return_value = "Solicitação recusada"
        bus.call.return_value = reply

        with (
            patch.dict(main.os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}),
            patch("main.QDBusConnection.sessionBus", return_value=bus),
            patch.object(self.window, "_show_shutdown_error") as show_error,
        ):
            self.window._request_shutdown()

        show_error.assert_called_once_with("Solicitação recusada")


if __name__ == "__main__":
    unittest.main()

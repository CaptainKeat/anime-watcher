import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton
from anime_watcher.phone_server import PhoneServer
import test_download_artwork_ui as artwork_fixture


class PhoneAccessUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): artwork_fixture.DownloadArtworkTests.setUpClass()
    def setUp(self):
        self.fixture = artwork_fixture.DownloadArtworkTests(); self.fixture.setUp(); self.window = self.fixture.window
        self.fixture.seed('Show')
        self.addresses = patch.object(self.window, '_phone_addresses', return_value=['10.20.30.40']); self.addresses.start()
        def create(db, root, data_root, **kwargs):
            return PhoneServer(db, root, data_root, addresses=kwargs['addresses'], port=0, host='127.0.0.1')
        self.factory = patch('anime_watcher.qt_ui.PhoneServer', side_effect=create); self.factory.start()
    def tearDown(self):
        self.fixture.tearDown(); self.factory.stop(); self.addresses.stop()
    def test_phone_access_is_opt_in_qr_refreshes_and_stop_disconnects(self):
        self.window.show_settings(); page = self.window.stack.currentWidget()
        enabled = page.findChild(QCheckBox, 'enablePhoneAccess'); self.assertFalse(enabled.isChecked())
        enabled.click(); server = self.window.phone_server; self.assertIsNotNone(server)
        qr = page.findChild(QLabel, 'phonePairingQr'); self.assertFalse(qr.pixmap().isNull())
        link = page.findChild(QLineEdit, 'phoneAccessLink'); previous = link.text(); self.assertIn('http://10.20.30.40:', previous)
        page.findChild(QPushButton, 'refreshPhonePairing').click(); self.assertNotEqual(link.text(), previous)
        enabled.click(); self.assertIsNone(self.window.phone_server); self.assertFalse(server.thread.is_alive()); self.assertEqual(link.text(), '')
    def test_unavailable_drive_shows_inline_error_without_starting_server(self):
        self.window.library_root = None; self.window.show_settings()
        page = self.window.stack.currentWidget(); enabled = page.findChild(QCheckBox, 'enablePhoneAccess'); enabled.click()
        self.assertFalse(enabled.isChecked()); self.assertIsNone(self.window.phone_server)
        self.assertIn('library folder', page.findChild(QLabel, 'phoneAccessStatus').text())
    def test_profile_switch_closes_server_and_cannot_share_previous_profile(self):
        self.window.show_settings(); self.window.phone_enabled.click(); server = self.window.phone_server
        profile = self.window.profile_manager.create('Other profile')
        self.window.profile_combo.addItem(profile.name, profile.id); self.window.profile_combo.setCurrentIndex(self.window.profile_combo.count()-1)
        self.window._switch_profile(); self.assertIsNone(self.window.phone_server); self.assertFalse(server.thread.is_alive())
    def test_window_close_stops_server(self):
        self.window.show_settings(); self.window.phone_enabled.click(); server = self.window.phone_server
        self.window.close(); self.assertIsNone(self.window.phone_server); self.assertFalse(server.thread.is_alive())

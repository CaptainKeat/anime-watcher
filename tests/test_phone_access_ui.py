import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtNetwork import QHostAddress, QNetworkAddressEntry, QNetworkInterface
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton
from anime_watcher.phone_server import PhoneServer
from anime_watcher.qt_ui import AnimeWatcherWindow
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
        self.factory = patch('anime_watcher.qt_ui.PhoneServer', side_effect=create); self.server_factory = self.factory.start()
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

    def test_connection_labels_select_the_matching_qr_address(self):
        connections = [('10.20.30.40', 'Ethernet — 10.20.30.40'), ('10.20.30.41', 'Wi-Fi — 10.20.30.41')]
        with patch.object(self.window, '_phone_connections', return_value=connections), patch.object(self.window, '_phone_addresses', return_value=[ip for ip, _ in connections]):
            self.window.show_settings(); self.window.phone_enabled.click()
            selector = self.window.phone_address
            self.assertEqual(selector.currentText(), connections[0][1])
            self.assertIn('http://10.20.30.40:', self.window.phone_link.text())
            selector.setCurrentIndex(1)
            self.assertEqual(selector.currentText(), connections[1][1])
            self.assertIn('http://10.20.30.41:', self.window.phone_link.text())
            self.window._new_phone_pairing()
            self.assertEqual(selector.currentData(), connections[1][0])

    def test_connecting_network_after_opening_settings_refreshes_the_qr(self):
        with patch.object(self.window, '_phone_addresses', return_value=[]) as addresses, patch.object(self.window, '_phone_connections', return_value=[]) as connections:
            self.window.show_settings(); self.assertEqual(self.window.phone_address.count(), 0)
            addresses.return_value = ['10.20.30.40']
            connections.return_value = [('10.20.30.40', 'Ethernet — 10.20.30.40')]
            self.window.phone_enabled.click()
            self.assertTrue(self.window.phone_enabled.isChecked())
            self.assertIn('http://10.20.30.40:', self.window.phone_link.text())

    def test_no_real_network_does_not_start_a_virtual_only_server(self):
        with patch.object(self.window, '_phone_addresses', return_value=[]), patch.object(self.window, '_phone_connections', return_value=[]):
            self.window.show_settings(); self.window.phone_enabled.click()
            self.assertFalse(self.window.phone_enabled.isChecked())
            self.assertIsNone(self.window.phone_server)
            self.assertIn('Ethernet', self.window.phone_status.text())
            self.server_factory.assert_not_called()


class PhoneNetworkSelectionTests(unittest.TestCase):
    def adapter(self, name, kind, ips, running=True):
        entries = []
        for ip in ips:
            entry = QNetworkAddressEntry(); entry.setIp(QHostAddress(ip)); entries.append(entry)
        flags = QNetworkInterface.InterfaceFlag.IsUp
        if running: flags |= QNetworkInterface.InterfaceFlag.IsRunning
        return SimpleNamespace(name=lambda: name, humanReadableName=lambda: name,
                               flags=lambda: flags, type=lambda: kind, addressEntries=lambda: entries)

    def connections(self, adapters):
        with patch('anime_watcher.qt_ui.QNetworkInterface.allInterfaces', return_value=adapters):
            return AnimeWatcherWindow._phone_connections(None)

    def test_wsl_and_vpn_ethernet_adapters_cannot_precede_the_home_network(self):
        types = QNetworkInterface.InterfaceType
        adapters = [self.adapter('vEthernet (WSL (Hyper-V firewall))', types.Ethernet, ['172.19.32.1']),
                    self.adapter('NordLynx', types.Ethernet, ['10.5.0.2']),
                    self.adapter('Wi-Fi', types.Wifi, ['192.168.10.25']),
                    self.adapter('Ethernet', types.Ethernet, ['192.168.10.24'])]
        self.assertEqual(self.connections(adapters), [('192.168.10.24', 'Ethernet — 192.168.10.24'), ('192.168.10.25', 'Wi-Fi — 192.168.10.25')])

    def test_physical_hotspot_remains_available_ahead_of_another_lan(self):
        types = QNetworkInterface.InterfaceType
        adapters = [self.adapter('Ethernet', types.Ethernet, ['192.168.10.24']),
                    self.adapter('Wi-Fi', types.Wifi, ['172.20.10.2'])]
        self.assertEqual(self.connections(adapters)[0], ('172.20.10.2', 'Wi-Fi — 172.20.10.2'))

    def test_unplugged_virtual_and_non_lan_addresses_are_not_offered(self):
        types = QNetworkInterface.InterfaceType
        adapters = [self.adapter('Ethernet', types.Ethernet, ['192.168.10.24'], running=False),
                    self.adapter('VirtualBox Host-Only', types.Ethernet, ['192.168.56.1']),
                    self.adapter('Tailscale', types.Unknown, ['100.70.20.1']),
                    self.adapter('Wi-Fi', types.Wifi, ['127.0.0.1', '169.254.3.2', '0.0.0.0', '8.8.8.8', '::1'])]
        self.assertEqual(self.connections(adapters), [])

    def test_addresses_come_from_each_computer_and_duplicates_are_removed(self):
        types = QNetworkInterface.InterfaceType
        adapters = [self.adapter('Wi-Fi', types.Wifi, ['10.44.55.66', '10.44.55.66'])]
        self.assertEqual(self.connections(adapters), [('10.44.55.66', 'Wi-Fi — 10.44.55.66')])

import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QPushButton
import test_phone_access_ui as phone_fixture


class SettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): phone_fixture.PhoneAccessUiTests.setUpClass()

    def setUp(self):
        self.fixture = phone_fixture.PhoneAccessUiTests(); self.fixture.setUp()
        self.window = self.fixture.window; self.window.show_settings()

    def tearDown(self): self.fixture.tearDown()

    def test_sections_group_existing_controls_and_remember_selection(self):
        tabs = self.window.settings_tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ['Library', 'Phone access', 'Updates', 'Shortcuts', 'Connections'])
        for index, widget in [(0,self.window.library_entry),(0,self.window.profile_combo),(0,self.window.backup_combo),
                              (1,self.window.phone_enabled),(2,self.window.check_update_button),(3,self.window.keybinding_edits['play_pause']),
                              (4,self.window.anilist_client_id),(4,self.window.provider_entry)]:
            self.assertTrue(tabs.widget(index).isAncestorOf(widget))
        tabs.setCurrentIndex(4); self.window.show_home(); self.window.show_settings()
        self.assertEqual(self.window.settings_tabs.currentIndex(),4)

    def test_phone_off_has_no_empty_pairing_area_and_on_shows_labeled_controls(self):
        self.window.settings_tabs.setCurrentIndex(1)
        self.assertTrue(self.window.phone_pairing_panel.isHidden()); self.assertEqual(self.window.phone_link.text(),'')
        self.assertEqual(self.window.phone_state_badge.text(),'Sharing off'); self.assertFalse(self.window.phone_firewall_button.isEnabled())
        self.window.phone_enabled.click()
        self.assertFalse(self.window.phone_pairing_panel.isHidden()); self.assertEqual(self.window.phone_state_badge.text(),'Sharing on')
        self.assertEqual(self.window.phone_address.accessibleName(),'Connection')
        self.assertEqual(self.window.phone_link.accessibleName(),'Open this link in Safari')
        self.assertFalse(self.window.phone_qr.pixmap().isNull())
        self.window.phone_enabled.click(); self.assertTrue(self.window.phone_pairing_panel.isHidden())
        self.assertEqual(self.window.phone_state_badge.text(),'Sharing off')

    def test_phone_error_keeps_form_collapsed_and_shows_attention_state(self):
        self.window.library_root=None; self.window.phone_enabled.click()
        self.assertTrue(self.window.phone_pairing_panel.isHidden())
        self.assertEqual(self.window.phone_state_badge.text(),'Needs attention')
        self.assertIn('library folder',self.window.phone_status.text())

    def test_switching_tabs_keeps_unsaved_fields_and_phone_session(self):
        self.window.library_entry.setText('an unsaved folder')
        self.window.phone_enabled.click(); server=self.window.phone_server; link=self.window.phone_link.text()
        for index in range(5): self.window.settings_tabs.setCurrentIndex(index)
        self.assertEqual(self.window.library_entry.text(),'an unsaved folder')
        self.assertIs(self.window.phone_server,server); self.assertEqual(self.window.phone_link.text(),link)

    def test_shortcut_validation_and_save_are_inline(self):
        self.window.settings_tabs.setCurrentIndex(3)
        with patch('anime_watcher.qt_ui.QMessageBox.warning',side_effect=AssertionError('No popup')), patch('anime_watcher.qt_ui.QMessageBox.information',side_effect=AssertionError('No popup')):
            self.window.keybinding_edits['play_pause'].clear(); self.window._save_keybindings()
            self.assertIn('Choose a shortcut',self.window.shortcuts_status.text()); self.assertEqual(self.window.db.setting('keybindings',{}),{})
            self.window.keybinding_edits['play_pause'].setKeySequence(QKeySequence('F')); self.window._save_keybindings()
            self.assertIn('unique',self.window.shortcuts_status.text())
            self.window.keybinding_edits['play_pause'].setKeySequence(QKeySequence('K')); self.window._save_keybindings()
            self.assertEqual(self.window.db.setting('keybindings')['play_pause'],'K'); self.assertIn('saved',self.window.shortcuts_status.text())

    def test_reset_shortcuts_does_not_change_saved_settings_until_save(self):
        self.window.keybinding_edits['play_pause'].setKeySequence(QKeySequence('K')); self.window._save_keybindings()
        self.window.stack.currentWidget().findChild(QPushButton,'resetSettingsShortcuts').click()
        self.assertEqual(self.window.keybinding_edits['play_pause'].keySequence().toString(),'Space')
        self.assertEqual(self.window.db.setting('keybindings')['play_pause'],'K')
        self.window._save_keybindings(); self.assertEqual(self.window.db.setting('keybindings')['play_pause'],'Space')

    def test_updates_preferences_still_save_for_active_profile(self):
        self.window.settings_tabs.setCurrentIndex(2); self.window.app_update_auto_check.click()
        self.assertIn('startup and every 6 hours', self.window.app_update_auto_check.text())
        with patch.object(self.window, '_check_for_app_update') as check:
            self.window.check_update_button.click(); check.assert_called_once_with(manual=True)
        self.assertFalse(self.window.db.setting('app_update_auto_check'))
        self.window.show_home(); QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete); self.window.show_settings()
        self.assertFalse(self.window.app_update_auto_check.isChecked())


if __name__=='__main__': unittest.main()

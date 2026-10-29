import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
import shortcut_kit as kit


XML_HEAD = '<?xml version="1.0"?><channel name="xfce4-keyboard-shortcuts"><property name="commands"><property name="{section}">'
XML_TAIL = '</property></property><property name="xfwm4"><property name="{section}">{xfwm}</property></property></channel>'


def xml(commands, xfwm='', section='custom'):
    return XML_HEAD.format(section=section) + commands + XML_TAIL.format(xfwm=xfwm, section=section)


class ShortcutKitTests(unittest.TestCase):
    def test_export_keeps_only_added_and_changed_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); current, system, output = folder/'current.xml', folder/'system.xml', folder/'out.json'
            system.write_text(xml('<property name="&lt;Alt&gt;F2" type="string" value="default-run"/>', section='default'))
            current.write_text(xml('<property name="&lt;Alt&gt;F2" type="string" value="my-run"/><property name="&lt;Primary&gt;a" type="string" value="/tmp/home/bin/tool"/>', '<property name="&lt;Alt&gt;F4" type="string" value="close_window_key"/>'))
            data = kit.export_bundle(output, current, system, home='/tmp/home', scope='custom')
            self.assertEqual([(x['group'], x['key']) for x in data['shortcuts']], [('commands', '<Alt>F2'), ('commands', '<Primary>a'), ('xfwm4', '<Alt>F4')])
            self.assertEqual(data['shortcuts'][1]['command'], '${HOME}/bin/tool')
            self.assertEqual(json.loads(output.read_text())['format_version'], 1)

    @patch('shortcut_kit.shutil.which', return_value='/usr/bin/xfconf-query')
    @patch('shortcut_kit.set_value')
    @patch('shortcut_kit.query')
    def test_import_skips_conflict_and_writes_backup(self, query, set_value, _which):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); bundle = folder/'bundle.json'
            bundle.write_text(json.dumps({'format_version': 1, 'desktop': 'xfce', 'shortcuts': [
                {'group': 'commands', 'key': '<Primary>a', 'command': '${HOME}/tool'},
                {'group': 'xfwm4', 'key': '<Alt>F4', 'command': 'close_window_key'}]}))
            query.side_effect = ['other', None, 'true']
            changes, skipped, backup = kit.import_bundle(bundle, home=folder/'newhome', state_root=folder/'state')
            self.assertEqual(changes, [('/xfwm4/custom/<Alt>F4', 'close_window_key')])
            self.assertEqual(len(skipped), 1)
            self.assertTrue(backup.is_file())
            self.assertEqual(json.loads(backup.read_text())['entries'][0]['value'], None)
            set_value.assert_called_once_with('/xfwm4/custom/<Alt>F4', 'close_window_key')

    @patch('shortcut_kit.shutil.which', return_value='/usr/bin/xfconf-query')
    @patch('shortcut_kit.query', return_value=None)
    def test_dry_run_does_not_create_backup(self, _query, _which):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); bundle = folder/'bundle.json'
            bundle.write_text(json.dumps({'format_version': 1, 'desktop': 'xfce', 'shortcuts': [{'group': 'commands', 'key': 'F9', 'command': 'tool'}]}))
            changes, skipped, backup = kit.import_bundle(bundle, dry_run=True, state_root=folder/'state')
            self.assertEqual(len(changes), 1); self.assertFalse(skipped); self.assertIsNone(backup)

    def test_all_exports_defaults_and_super_combos_but_not_disabled_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            system, current = folder/'system.xml', folder/'current.xml'
            bindings = ('<property name="&lt;Primary&gt;&lt;Alt&gt;t" type="string" value="exo-open --launch TerminalEmulator"/>'
                        '<property name="&lt;Super&gt;e" type="string" value="thunar"/>')
            system.write_text(xml(bindings + '<property name="F9" type="string" value="disabled"/>', section='default'))
            current.write_text(xml(bindings + '<property name="override" type="bool" value="true"/>'))
            result = kit.export_bundle(folder/'out.json', current, system, home=folder)
            self.assertEqual({x['key'] for x in result['shortcuts']}, {'<Primary><Alt>t', '<Super>e'})
            self.assertEqual(result['scope'], 'all')
            current.write_text(xml(''))
            self.assertEqual(len(kit.active_shortcuts(current, system)), 3)

    @patch.dict('os.environ', {'XDG_SESSION_TYPE': 'x11'})
    @patch('shortcut_kit.shutil.which', return_value='/usr/bin/xcape')
    def test_super_tap_install_and_restore(self, _which):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': str(folder/'config')}):
                bundle = folder/'bundle.json'
                bundle.write_text(json.dumps({'format_version': 1, 'desktop': 'xfce', 'shortcuts': [], 'super_tap': 'Super_L=Alt_L|F1'}))
                _, _, backup = kit.import_bundle(bundle, home=folder, state_root=folder/'state')
                path = folder/'config/autostart/xcape.desktop'
                self.assertIn("Exec=xcape -e 'Super_L=Alt_L|F1'", path.read_text())
                self.assertEqual(kit.super_autostart(folder), 'Super_L=Alt_L|F1')
                kit.restore(backup)
                self.assertFalse(path.exists())

    @patch('shortcut_kit.shutil.which', return_value='/usr/bin/xfconf-query')
    @patch('shortcut_kit.set_value')
    @patch('shortcut_kit.query', return_value=None)
    def test_fresh_xfce_enables_custom_bindings(self, _query, setter, _which):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            bundle = folder/'bundle.json'
            bundle.write_text(json.dumps({'format_version': 1, 'desktop': 'xfce', 'shortcuts': [{'group': 'commands', 'key': '<Primary><Alt>t', 'command': 'terminal'}]}))
            kit.import_bundle(bundle, state_root=folder/'state')
            setter.assert_any_call('/commands/custom/override', 'true', 'bool')

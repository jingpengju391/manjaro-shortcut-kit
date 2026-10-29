"""Real xfconf round trip on a private bus and temporary configuration only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def child():
    sys.path.insert(0, str(ROOT))
    import shortcut_kit as kit
    state = Path(os.environ['XDG_STATE_HOME'])
    config = Path(os.environ['XDG_CONFIG_HOME'])
    bundle = ROOT / 'payload/user-shortcuts.json'
    changes, skipped, backup = kit.import_bundle(bundle, conflict='replace', state_root=state/'backups')
    assert not skipped, skipped
    assert len(changes) == len(kit.read_bundle(bundle)['shortcuts'])
    assert kit.query('/commands/custom/<Primary><Alt>t') == 'exo-open --launch TerminalEmulator'
    assert kit.query('/commands/custom/<Super>e') == 'thunar'
    assert kit.query('/commands/custom/override') == 'true'
    assert (config/'autostart/xcape.desktop').is_file()
    assert kit.import_bundle(bundle, state_root=state/'backups')[2] is None
    # Reproduce the destination machine: migration keys already exist alongside
    # the destination's F9/F10 defaults. A repeat install must repair this too.
    kit.set_value('/xfwm4/custom/<Alt>F10', 'maximize_window_key')
    kit.set_value('/xfwm4/custom/<Alt>F9', 'hide_window_key')
    changes, skipped, repair = kit.import_bundle(bundle, conflict='replace', state_root=state/'backups')
    assert not skipped
    assert kit.query('/xfwm4/custom/<Alt>F10') is None
    assert kit.query('/xfwm4/custom/<Alt>F9') is None
    assert kit.query('/xfwm4/custom/<Alt>Up') == 'maximize_window_key'
    assert kit.query('/xfwm4/custom/<Alt>Down') == 'hide_window_key'
    assert kit.import_bundle(bundle, conflict='replace', state_root=state/'backups')[2] is None
    kit.restore(repair)
    assert kit.query('/xfwm4/custom/<Alt>F10') == 'maximize_window_key'
    assert kit.query('/xfwm4/custom/<Alt>F9') == 'hide_window_key'
    kit.reset('/xfwm4/custom/<Alt>F10')
    kit.reset('/xfwm4/custom/<Alt>F9')
    kit.restore(backup)
    assert kit.query('/commands/custom/<Primary><Alt>t') is None
    assert kit.query('/commands/custom/override') is None
    assert not (config/'autostart/xcape.desktop').exists()
    print('PASS: all bindings, terminal, Super, duplicate window actions, idempotency, backup and restore')


if __name__ == '__main__':
    if '--child' in sys.argv:
        child()
    else:
        with tempfile.TemporaryDirectory(prefix='shortcut-kit-smoke-') as folder:
            env = dict(os.environ, XDG_CONFIG_HOME=folder+'/config', XDG_STATE_HOME=folder+'/state',
                       XDG_CACHE_HOME=folder+'/cache', XDG_CURRENT_DESKTOP='XFCE', XDG_SESSION_TYPE='x11')
            subprocess.run(['dbus-run-session', '--', sys.executable, __file__, '--child'], env=env, check=True)
            # xfconfd flushes its temporary XML asynchronously when its private bus exits.
            time.sleep(1)

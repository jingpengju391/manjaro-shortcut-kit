#!/usr/bin/env python3
"""Export and restore only user-added or user-changed Xfce shortcuts."""
import argparse
import datetime as dt
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

FORMAT_VERSION = 1
CHANNEL = 'xfce4-keyboard-shortcuts'
GROUPS = ('commands', 'xfwm4')
DEFAULT_XML = Path('/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml')


def config_xml(home=None):
    home = Path(home or Path.home())
    base = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config')))
    return base / 'xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml'


def normalize_key(key):
    """Xfce may serialize equivalent modifier names/orders differently."""
    names = {'<Control>': '<Primary>', '<Primary>': '<Primary>', '<Alt>': '<Alt>',
             '<Shift>': '<Shift>', '<Super>': '<Super>'}
    modifiers = []
    rest = key
    import re
    for token in re.findall(r'<[^>]+>', key):
        rest = rest.replace(token, '', 1)
        modifiers.append(names.get(token, token))
    order = {'<Primary>': 0, '<Alt>': 1, '<Shift>': 2, '<Super>': 3}
    return ''.join(sorted(set(modifiers), key=lambda x: order.get(x, 99))) + rest


def node_map(xml_path, section='custom', raw_keys=False):
    """Return direct shortcut properties from the requested Xfce section."""
    root = ET.parse(xml_path).getroot()
    result = {}
    for group in GROUPS:
        parent = root.find("./property[@name='%s']/property[@name='%s']" % (group, section))
        if parent is None:
            continue
        for node in parent.findall('property'):
            # `override` controls Xfce's fallback behavior, not a shortcut.
            if node.get('name') == 'override' or node.get('type') != 'string':
                continue
            key = node.get('name') if raw_keys else normalize_key(node.get('name'))
            result[(group, key)] = node.get('value', '')
    return result


def user_shortcuts(current, system):
    """Bindings whose value differs from Xfce's packaged defaults."""
    current_map = node_map(current, 'custom')
    raw_map = node_map(current, 'custom', raw_keys=True)
    # Packaged Xfce defaults live under `default`, not `custom`.
    system_map = node_map(system, 'default')
    return [
        {'group': group, 'key': next(raw for (raw_group, raw), raw_value in raw_map.items()
                                     if raw_group == group and raw_value == value and normalize_key(raw) == key), 'command': value}
        for (group, key), value in sorted(current_map.items())
        if system_map.get((group, key)) != value
    ]


def portable(command, home):
    return command.replace(str(home), '${HOME}')


def native(command, home):
    return command.replace('${HOME}', str(home))


def export_bundle(output, current=None, system=DEFAULT_XML, home=None):
    home = Path(home or Path.home())
    current = Path(current or config_xml(home))
    system = Path(system)
    if not current.is_file():
        raise RuntimeError('找不到当前 Xfce 快捷键配置：' + str(current))
    if not system.is_file():
        raise RuntimeError('找不到 Xfce 系统默认配置，拒绝导出以免把系统快捷键误带走：' + str(system))
    bindings = user_shortcuts(current, system)
    bundle = {
        'format_version': FORMAT_VERSION,
        'desktop': 'xfce',
        'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'shortcuts': [{**entry, 'command': portable(entry['command'], home)} for entry in bindings],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
    return bundle


def read_bundle(path):
    data = json.loads(Path(path).read_text())
    if data.get('format_version') != FORMAT_VERSION or data.get('desktop') != 'xfce':
        raise RuntimeError('不是受支持的 Xfce 快捷键迁移文件。')
    items = data.get('shortcuts')
    if not isinstance(items, list) or any(not isinstance(x, dict) or x.get('group') not in GROUPS or not isinstance(x.get('key'), str) or not isinstance(x.get('command'), str) for x in items):
        raise RuntimeError('快捷键迁移文件格式无效。')
    return data


def query(path):
    result = subprocess.run(['xfconf-query', '-c', CHANNEL, '-p', path], capture_output=True, text=True)
    return result.stdout.rstrip('\n') if result.returncode == 0 else None


def set_value(path, value):
    subprocess.run(['xfconf-query', '-c', CHANNEL, '-p', path, '--create', '-t', 'string', '-s', value], check=True)


def reset(path):
    subprocess.run(['xfconf-query', '-c', CHANNEL, '-p', path, '--reset'], check=True)


def desktop():
    name = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    if 'GNOME' in name:
        return 'gnome'
    if 'KDE' in name or 'PLASMA' in name:
        return 'kde'
    return 'xfce'


def gsettings(*args):
    return subprocess.check_output(['gsettings', *args], text=True).strip()


def import_gnome(bundle_path, conflict='skip', dry_run=False, home=None, state_root=None):
    """Install command shortcuts through GNOME's supported custom-keybinding API."""
    if not shutil.which('gsettings') or not shutil.which('dconf'):
        raise RuntimeError('GNOME 导入需要 gsettings 和 dconf。')
    schema = 'org.gnome.settings-daemon.plugins.media-keys'
    if schema not in gsettings('list-schemas').splitlines():
        raise RuntimeError('此 GNOME 未提供自定义全局快捷键接口。')
    bundle = read_bundle(bundle_path)
    home = Path(home or Path.home())
    base = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/'
    paths = ast.literal_eval(gsettings('get', schema, 'custom-keybindings').removeprefix('@as '))
    existing = {p: ast.literal_eval(gsettings('get', 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:' + p, 'binding')) for p in paths}
    changes, skipped, backup = [], [], []
    for item in bundle['shortcuts']:
        if item['group'] != 'commands':
            continue  # Xfwm action names have no safe GNOME equivalent.
        key = item['key'].replace('<Primary>', '<Control>')
        ident = hashlib.sha256((item['group'] + '\0' + item['key']).encode()).hexdigest()[:16]
        path = base + 'manjaro-shortcut-kit-' + ident + '/'
        command = native(item['command'], home)
        occupied = next((p for p, binding in existing.items() if binding == key and p != path), None)
        old_command = gsettings('get', 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:' + path, 'command') if path in paths else None
        if occupied or (old_command is not None and ast.literal_eval(old_command) != command and conflict == 'skip'):
            skipped.append((key, occupied or path, command)); continue
        if old_command is not None and ast.literal_eval(old_command) == command:
            continue
        for suffix in ('name', 'command', 'binding'):
            target = path + suffix
            backup.append({'path': target, 'value': subprocess.run(['dconf', 'read', target], capture_output=True, text=True).stdout.strip()})
        if path not in paths:
            backup.append({'path': base[:-1], 'value': subprocess.run(['dconf', 'read', base[:-1]], capture_output=True, text=True).stdout.strip()})
        changes.append((path, key, command))
    if dry_run:
        return changes, skipped, None
    state_root = Path(state_root or home / '.local/state/manjaro-shortcut-kit/backups')
    backup_path = state_root / dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f') / 'restore.json'
    backup_path.parent.mkdir(parents=True, exist_ok=False)
    backup_path.write_text(json.dumps({'format_version': FORMAT_VERSION, 'backend': 'gnome', 'entries': backup}, ensure_ascii=False, indent=2) + '\n')
    for path, key, command in changes:
        target_schema = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:' + path
        for suffix, value in [('name', '迁移快捷键'), ('command', command), ('binding', key)]:
            subprocess.run(['gsettings', 'set', target_schema, suffix, repr(value)], check=True)
        if path not in paths: paths.append(path)
    if changes:
        subprocess.run(['gsettings', 'set', schema, 'custom-keybindings', repr(paths)], check=True)
    return changes, skipped, backup_path


def import_bundle(bundle_path, conflict='skip', dry_run=False, home=None, state_root=None):
    if not shutil.which('xfconf-query'):
        raise RuntimeError('未安装 xfconf-query；此迁移包仅适用于 Xfce。')
    bundle = read_bundle(bundle_path)
    home = Path(home or Path.home())
    changes, skipped, backup = [], [], []
    for item in bundle['shortcuts']:
        path = '/%s/custom/%s' % (item['group'], item['key'])
        wanted, existing = native(item['command'], home), query(path)
        if existing == wanted:
            continue
        if existing is not None and conflict == 'skip':
            skipped.append((path, existing, wanted))
            continue
        changes.append((path, wanted))
        backup.append({'path': path, 'value': existing})
    if dry_run:
        return changes, skipped, None
    state_root = Path(state_root or home / '.local/state/manjaro-shortcut-kit/backups')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = state_root / stamp / 'restore.json'
    backup_path.parent.mkdir(parents=True, exist_ok=False)
    backup_path.write_text(json.dumps({'format_version': FORMAT_VERSION, 'entries': backup}, ensure_ascii=False, indent=2) + '\n')
    for path, value in changes:
        set_value(path, value)
    return changes, skipped, backup_path


def restore(restore_file, dry_run=False):
    data = json.loads(Path(restore_file).read_text())
    if data.get('format_version') != FORMAT_VERSION or not isinstance(data.get('entries'), list):
        raise RuntimeError('恢复文件格式无效。')
    if dry_run:
        return len(data['entries'])
    for item in reversed(data['entries']):
        if data.get('backend') == 'gnome':
            command = ['dconf', 'reset', item['path']] if not item['value'] else ['dconf', 'write', item['path'], item['value']]
            subprocess.run(command, check=True)
        else:
            reset(item['path']) if item['value'] is None else set_value(item['path'], item['value'])
    return len(data['entries'])


def main():
    parser = argparse.ArgumentParser(description='迁移 Xfce 中自己添加或改写的快捷键。')
    sub = parser.add_subparsers(dest='action', required=True)
    exp = sub.add_parser('export', help='从当前电脑导出用户快捷键')
    exp.add_argument('--output', required=True)
    exp.add_argument('--current', help='用于测试或手动指定当前配置 XML')
    exp.add_argument('--system', default=str(DEFAULT_XML), help='系统默认配置 XML')
    imp = sub.add_parser('import', help='导入迁移文件')
    imp.add_argument('bundle')
    imp.add_argument('--conflict', choices=('skip', 'replace'), default='skip')
    imp.add_argument('--dry-run', action='store_true')
    imp.add_argument('--state-root')
    res = sub.add_parser('restore', help='恢复某次导入前的状态')
    res.add_argument('restore_file')
    res.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'export':
            data = export_bundle(args.output, args.current, args.system)
            print('已导出 %d 条用户快捷键：%s' % (len(data['shortcuts']), args.output))
        elif args.action == 'import':
            target = desktop()
            if target == 'gnome':
                changes, skipped, backup = import_gnome(args.bundle, args.conflict, args.dry_run, state_root=args.state_root)
            elif target == 'kde':
                raise RuntimeError('KDE Plasma 请使用 README 中的导入助手；KGlobalAccel 不能安全地把任意命令写成全局动作。')
            else:
                changes, skipped, backup = import_bundle(args.bundle, args.conflict, args.dry_run, state_root=args.state_root)
            print(('演练：' if args.dry_run else '') + '将写入 %d 条快捷键；跳过 %d 条冲突。' % (len(changes), len(skipped)))
            if backup: print('恢复文件：' + str(backup))
            for path, old, new in skipped: print('冲突，保留目标机设置：%s（当前：%s；迁移：%s）' % (path, old, new))
        else:
            print(('演练：' if args.dry_run else '') + '已恢复 %d 条快捷键。' % restore(args.restore_file, args.dry_run))
    except (RuntimeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, ET.ParseError) as error:
        raise SystemExit('操作失败：' + str(error))


if __name__ == '__main__':
    main()

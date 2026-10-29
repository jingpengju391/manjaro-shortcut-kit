#!/usr/bin/env python3
"""Export active Xfce global shortcuts, including desktop defaults and Super tap."""
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


def active_shortcuts(current, system):
    """Honor custom/override: do not resurrect defaults the user disabled."""
    root = ET.parse(current).getroot()
    result = []
    for group in GROUPS:
        custom = root.find("./property[@name='%s']/property[@name='custom']" % group)
        override = custom.find("property[@name='override']") if custom is not None else None
        source = current if override is not None and override.get('value') == 'true' else system
        section = 'custom' if source == current else 'default'
        for (provider, key), command in node_map(source, section, raw_keys=True).items():
            if provider == group:
                result.append({'group': group, 'key': key, 'command': command})
    return sorted(result, key=lambda x: (x['group'], x['key']))


def state_directory(home):
    return Path(os.environ.get('XDG_STATE_HOME', str(home / '.local/state'))) / 'manjaro-shortcut-kit/backups'


def super_autostart(home):
    config = config_xml(home).parents[3]
    path = config / 'autostart/xcape.desktop'
    if path.is_file():
        content = path.read_text()
        if "Exec=xcape -e 'Super_L=Alt_L|F1'" in content and 'Hidden=true' not in content:
            return 'Super_L=Alt_L|F1'
    return None


def export_bundle(output, current=None, system=DEFAULT_XML, home=None, scope='all'):
    home = Path(home or Path.home())
    current = Path(current or config_xml(home))
    system = Path(system)
    if not current.is_file():
        raise RuntimeError('找不到当前 Xfce 快捷键配置：' + str(current))
    if not system.is_file():
        raise RuntimeError('找不到 Xfce 系统默认配置，拒绝导出以免把系统快捷键误带走：' + str(system))
    bindings = active_shortcuts(current, system) if scope == 'all' else user_shortcuts(current, system)
    bundle = {
        'format_version': FORMAT_VERSION,
        'desktop': 'xfce',
        'scope': scope,
        'super_tap': super_autostart(home),
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


def set_value(path, value, value_type='string'):
    subprocess.run(['xfconf-query', '-c', CHANNEL, '-p', path, '--create', '-t', value_type, '-s', value], check=True)


def reset(path):
    subprocess.run(['xfconf-query', '-c', CHANNEL, '-p', path, '--reset'], check=True)


def desktop():
    name = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    if 'GNOME' in name:
        return 'gnome'
    if 'KDE' in name or 'PLASMA' in name:
        return 'kde'
    if 'XFCE' in name:
        return 'xfce'
    raise RuntimeError('无法识别桌面；请在已登录的 Xfce、GNOME 或 KDE 桌面运行。')


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
            skipped.append((item['key'], 'GNOME 尚未支持此 Xfwm 动作', item['command']))
            continue  # Xfwm action names have no safe GNOME equivalent.
        key = item['key'].replace('<Primary>', '<Control>')
        ident = hashlib.sha256((item['group'] + '\0' + item['key']).encode()).hexdigest()[:16]
        path = base + 'manjaro-shortcut-kit-' + ident + '/'
        command = native(item['command'], home)
        if command and command.split(maxsplit=1)[0] in {'xfce4-popup-whiskermenu', 'xfce4-appfinder', 'xfce4-screenshooter', 'xfce4-session-logout', 'xfce4-taskmanager', 'xfce4-display-settings', 'xfdesktop', 'xflock4', 'thunar', 'xkill'}:
            skipped.append((key, '此命令依赖 Xfce/X11，尚未转换为 GNOME 原生动作', command))
            continue
        if command == 'exo-open --launch TerminalEmulator':
            executable = next((x for x in ('kgx', 'gnome-terminal', 'ptyxis') if shutil.which(x)), None)
            if executable is None:
                skipped.append((key, '未找到 GNOME 终端程序', command)); continue
            command = executable
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
    state_root = Path(state_root or state_directory(home))
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
    file_backup = []
    autostart = None
    if bundle.get('super_tap'):
        if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            skipped.append(('Super_L', 'xcape 仅支持 X11', '打开应用菜单'))
        else:
            if not shutil.which('xcape'):
                raise RuntimeError('Win 单键需要 xcape，请先运行 sudo pacman -S --needed xcape，再重新导入。')
            autostart = config_xml(home).parents[3] / 'autostart/xcape.desktop'
            content = '[Desktop Entry]\nType=Application\nName=Win key menu\nExec=xcape -e \'Super_L=Alt_L|F1\'\nOnlyShowIn=XFCE;\nTerminal=false\nHidden=false\n'
            if autostart.is_symlink():
                raise RuntimeError('xcape.desktop 是符号链接，请先人工检查：' + str(autostart))
            old = autostart.read_text() if autostart.exists() else None
            if old is not None and "Exec=xcape -e 'Super_L=Alt_L|F1'" in old and 'Hidden=true' not in old:
                autostart = None
            elif old is not None and conflict == 'skip':
                skipped.append(('Super_L', '已有不同的 xcape 自启动配置', '打开应用菜单'))
                autostart = None
            else:
                file_backup.append({'path': str(autostart), 'value': old})
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
    for path, value in changes:
        print('快捷键：%s → %s' % (path, value))
    overrides = []
    for group in sorted({path.split('/')[1] for path, _ in changes}):
        path = '/' + group + '/custom/override'
        old = query(path)
        if old != 'true':
            backup.append({'path': path, 'value': old, 'type': 'bool'})
            overrides.append(path)
    if autostart:
        print('Win 单键：安装 xcape 自启动（下次登录生效）')
    if dry_run:
        return changes, skipped, None
    if not changes and not file_backup:
        return changes, skipped, None
    state_root = Path(state_root or state_directory(home))
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = state_root / stamp / 'restore.json'
    backup_path.parent.mkdir(parents=True, exist_ok=False)
    backup_path.write_text(json.dumps({'format_version': FORMAT_VERSION, 'entries': backup, 'files': file_backup}, ensure_ascii=False, indent=2) + '\n')
    print('修改前备份：' + str(backup_path), flush=True)
    if autostart:
        autostart.parent.mkdir(parents=True, exist_ok=True)
        autostart.write_text(content)
    for path, value in changes:
        set_value(path, value)
    for path in overrides:
        set_value(path, 'true', 'bool')
    return changes, skipped, backup_path


def restore(restore_file, dry_run=False):
    data = json.loads(Path(restore_file).read_text())
    if data.get('format_version') != FORMAT_VERSION or not isinstance(data.get('entries'), list):
        raise RuntimeError('恢复文件格式无效。')
    if dry_run:
        return len(data['entries']) + len(data.get('files', []))
    for item in data.get('files', []):
        path = Path(item['path'])
        if path.is_symlink():
            raise RuntimeError('恢复目标已变为符号链接：' + str(path))
        if item['value'] is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item['value'])
    for item in reversed(data['entries']):
        if data.get('backend') == 'gnome':
            command = ['dconf', 'reset', item['path']] if not item['value'] else ['dconf', 'write', item['path'], item['value']]
            subprocess.run(command, check=True)
        else:
            if item['value'] is None:
                reset(item['path'])
            else:
                set_value(item['path'], item['value'], item.get('type', 'string'))
    return len(data['entries'])


def main():
    parser = argparse.ArgumentParser(description='迁移当前全局快捷键，包括系统默认键及 Win 单键。')
    sub = parser.add_subparsers(dest='action', required=True)
    exp = sub.add_parser('export', help='从当前电脑导出用户快捷键')
    exp.add_argument('--output', required=True)
    exp.add_argument('--scope', choices=('all', 'custom'), default='all', help='默认 all：全部生效绑定；custom：仅差异')
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
            data = export_bundle(args.output, args.current, args.system, scope=args.scope)
            print('已导出 %d 条全局快捷键：%s；Win 单键：%s' % (len(data['shortcuts']), args.output, data.get('super_tap') or '无'))
        elif args.action == 'import':
            target = desktop()
            if target == 'gnome':
                changes, skipped, backup = import_gnome(args.bundle, args.conflict, args.dry_run, state_root=args.state_root)
            elif target == 'kde':
                raise RuntimeError('KDE Plasma 自动导入尚未实现；本次未迁移任何快捷键。')
            else:
                changes, skipped, backup = import_bundle(args.bundle, args.conflict, args.dry_run, state_root=args.state_root)
            print(('演练：将写入' if args.dry_run else '已写入') + ' %d 条快捷键；跳过 %d 条（冲突或不支持）。' % (len(changes), len(skipped)))
            if backup: print('恢复文件：' + str(backup))
            for path, old, new in skipped: print('未迁移：%s（原因/当前：%s；迁移：%s）' % (path, old, new))
        else:
            print(('演练：' if args.dry_run else '') + '已恢复 %d 条快捷键。' % restore(args.restore_file, args.dry_run))
    except (RuntimeError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, ET.ParseError) as error:
        raise SystemExit('操作失败：' + str(error))


if __name__ == '__main__':
    main()

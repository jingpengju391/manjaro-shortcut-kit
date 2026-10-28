#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID == 0 ]]; then
  echo '请以普通桌面用户运行，不要 sudo。' >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo '需要 Python 3。' >&2
  exit 1
fi
action=import
args=()
for arg in "$@"; do
  case "$arg" in
    --restore) action=restore ;;
    --check|--dry-run) args+=(--dry-run) ;;
    --replace) args+=(--conflict replace) ;;
    --help|-h) echo '用法：bash install.sh [--check|--dry-run] [--replace]；bash install.sh --restore 恢复最近一次导入。'; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done
if [[ $action == restore ]]; then
  latest=$(find "${XDG_STATE_HOME:-$HOME/.local/state}/manjaro-shortcut-kit/backups" -name restore.json -type f 2>/dev/null | sort | tail -n1 || true)
  [[ -n $latest ]] || { echo '没有可恢复的导入备份。' >&2; exit 1; }
  exec python3 shortcut_kit.py restore "$latest" "${args[@]}"
fi
exec python3 shortcut_kit.py import payload/user-shortcuts.json "${args[@]}"

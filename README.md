# Manjaro Shortcut Kit · 全局快捷键迁移包

默认迁移当前 Xfce 桌面全部生效的全局快捷键，包括系统默认键、用户修改/新增的键、窗口管理器绑定和左 Win 单键菜单。旧版仅保存与默认值不同的项目，漏掉了 Ctrl+Alt+T、Win+E、Win+R 等；现在已取消该过滤。

## 新电脑安装 / 更新

在已经登录的 Xfce 图形桌面运行（不要 sudo 整个安装器）：

```bash
git clone https://github.com/jingpengju391/manjaro-shortcut-kit.git
cd manjaro-shortcut-kit
bash install.sh --check
bash install.sh --replace
```

已有项目先执行 `git pull --ff-only`。`--replace` 将迁移包中的按键设为旧电脑的对应动作，修改前自动备份。对 Xfwm 窗口动作，还会清理目标电脑上同一动作的旧绑定；其他无关绑定保留。省略该参数会保留目标电脑已占用的按键及同动作旧绑定，并逐项报告冲突。

### 修复 Alt+↑/↓ 无效

旧版本合并配置后，可能同时留下 Alt+F10 和 Alt+↑（最大化／还原）、Alt+F9 和 Alt+↓（最小化）。Xfwm 每个动作只使用一个绑定，因此重复配置可能使方向键失效。新版通过实时 xfconf 查询发现重复项，备份后移除旧键，并重新注册迁移键。即使方向键的配置原本已经存在，也会执行修复。

在目标电脑更新后运行：

```bash
git pull --ff-only
bash install.sh --check --replace
bash install.sh --replace
```

安装会通知正在运行的窗口管理器更新绑定；若仍无响应，注销并重新登录后再试。`bash install.sh --restore` 可恢复本次清理前的绑定。此修复针对同动作重复绑定，不代表其他 Alt 失效原因都已排除。

| 按键 | 源电脑动作 |
| --- | --- |
| Ctrl+Alt+T | 默认终端 |
| Win 单键（左 Super） | 应用菜单 |
| Win+E / Win+R | 文件管理器 / 运行程序 |
| Alt+Tab / Alt+Shift+Tab | 切换窗口 |
| Alt+Up / Alt+Down | 最大化与还原切换 / 最小化 |
| Print / Alt+Print / Shift+Print | 截图 / 窗口截图 / 区域截图 |
| Ctrl+Shift+A | Flameshot |
| Ctrl+Alt+W | 微信 |
| Ctrl+Alt+M / O / , / . | 音乐显示、播放暂停、上一首、下一首 |

完整的 81 条绑定见 `payload/user-shortcuts.json`，包含工作区切换和窗口移动快捷键。

## Win 单键

源电脑使用 `~/.config/autostart/xcape.desktop` 将左 Super 映射为 Alt+F1。导出时识别此设置，导入时备份并安装自启动项；**重新登录后生效**，不会启动重复 xcape 进程。

若检查提示缺少 xcape，先安装：

```bash
sudo pacman -S --needed xcape
```

该机制只适用于 X11。Xfce Wayland 会明确报告无法迁移 Win 单键。

## 恢复

```bash
bash install.sh --restore
```

备份位于 `~/.local/state/manjaro-shortcut-kit/backups/`（支持 XDG_STATE_HOME），包含改动前的快捷键和 xcape 自启动文件。恢复自启动文件后需重新登录。无实际改动的 Xfce 导入不会生成空备份。

## 刷新源电脑快照

```bash
python3 shortcut_kit.py export --output payload/user-shortcuts.json
python3 -m unittest discover -s tests -v
```

读取 Xfce 用户配置的 commands/custom、xfwm4/custom；当组未启用 custom/override 时才使用系统 default。不会把已被用户停用的默认键重新加入源快照。Win 单键设置也会检测并写入快照。若确实只需要旧版的差异导出，可指定 `--scope custom`。

## 桌面兼容范围

- **Xfce**：完整导入源快照的命令键、窗口管理器键；X11 支持源电脑的 Win 单键映射。
- **GNOME**：目前仅部分命令键可导入，Ctrl+Alt+T 会选择已安装的 GNOME 终端；Xfce 专属命令和窗口动作会逐项报告未支持。Win 单键保留 GNOME 原生行为。
- **KDE Plasma**：自动导入尚未实现，运行会明确停止。旧 README 提及的“KDE 导入助手”并不存在，不能认为已支持。

本次修复验证范围是 Xfce。GNOME/KDE 仍不能完整等价恢复所有 Xfce 动作。迁移包不安装命令所需应用或脚本，微信、音乐、Flameshot 等仍需单独安装。应用内部的编辑器快捷键不属于桌面全局键，不在此包范围内。

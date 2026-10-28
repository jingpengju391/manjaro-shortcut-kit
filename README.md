# Manjaro Shortcut Kit · 用户快捷键迁移包

迁移这台 Xfce 电脑中**自己新增或改写的全局快捷键**。它不导出 Xfce 自带的默认键，因此不会把 Alt+Tab、锁屏、默认截图等系统绑定覆盖到新电脑。

当前包内已经保存了此电脑的用户快捷键。命令中的当前用户目录会以 `${HOME}` 保存，导入新电脑时会自动替换为新电脑的实际家目录。

## 新电脑导入

在已登录的 Xfce 桌面中运行：

```bash
git clone https://github.com/jingpengju391/manjaro-shortcut-kit.git
cd manjaro-shortcut-kit
bash install.sh --check    # 只预览，不写入
bash install.sh            # 默认保留新电脑已有的冲突绑定
```

若确认迁移包应覆盖新电脑已有的同一快捷键：

```bash
bash install.sh --replace
```

每次实际导入前，目标机中将被改写的项目会保存在 `~/.local/state/manjaro-shortcut-kit/backups/`。恢复最近一次导入：

```bash
bash install.sh --restore
```

本项目只迁移快捷键本身，不安装快捷键命令所调用的应用或脚本。例如微信、音乐播放器的启动命令仍需由对应的迁移包或软件安装完成。

## Manjaro 桌面版本兼容性

| 目标版本 | 可迁移内容 | 行为 |
| --- | --- | --- |
| Xfce | 命令快捷键、改写过的 Xfwm 窗口快捷键 | 自动导入、冲突默认保留目标机设置 |
| GNOME | 命令快捷键 | 自动使用 GNOME 官方的 `custom-keybindings` 接口导入；Xfwm 专属窗口动作跳过 |
| KDE Plasma | 命令快捷键 | 由 KDE 导入助手处理；不把 Xfwm 动作伪装成 KWin 动作 |

KDE 的 KGlobalAccel 必须同时注册一个常驻动作接收器，不能像 Xfce/GNOME 那样安全地只写一条“按键→shell 命令”的配置。本项目因此不会直接篡改 `kglobalshortcutsrc`；KDE 导入助手会在后续版本作为独立、可审查的用户服务提供。

## 在旧电脑刷新迁移文件

新增或修改快捷键后，在此仓库根目录执行：

```bash
python3 shortcut_kit.py export --output payload/user-shortcuts.json
python3 -m unittest discover -s tests -v
git add payload/user-shortcuts.json && git commit -m '更新用户快捷键'
```

导出逻辑会将 `~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml` 与系统的 `/etc/xdg/.../xfce4-keyboard-shortcuts.xml` 比较，只保留有差异的 `commands/custom` 和 `xfwm4/custom` 项。找不到系统默认文件时会拒绝导出，而不是误将所有系统默认项打包。

## 限制

当前导出端面向 Manjaro/Arch 的 **Xfce**；GNOME 可作为自动导入目标。KDE 的安全导入需要常驻 KGlobalAccel 接收器，目前会明确停止而不伪造“已迁移”的结果。

# Windows + WSL2 使用指南

本文面向 Windows 平台上的 OpenClaw、WorkBuddy 或其他个人 Agent。目标是让 Agent 可以按步骤协助用户完成 mini-note 安装，同时清楚说明需要用户授权的动作、资源成本和性能风险。

## 1. 结论

mini-note 当前推荐在 Windows 上通过 WSL2 使用，不推荐原生 PowerShell/CMD 直接运行。

原因：

- `install.sh`、`run.sh`、`import.sh`、`verify.sh` 都是 bash 脚本。
- `import.sh` 使用 `find`、`stat`、`cp`、`ls`、`date` 等 POSIX 工具。
- `mini-note.skill.md` 中的命令映射默认是 `./run.sh ...` 和 `./import.sh ...`。
- PID 锁清理使用 Unix 风格的进程探测语义，WSL2 中更符合预期。

因此，Windows 用户的标准部署形态是：

```text
Windows
  └─ WSL2 Ubuntu
       └─ ~/mini-note
            ├─ ./run.sh
            ├─ ./import.sh
            └─ raw/ wiki/ meta/ .state/
```

## 2. Agent 执行边界

OpenClaw / WorkBuddy 可以协助执行安装，但不能静默安装 WSL2。

安装 WSL2 前必须先向用户确认：

- 是否允许以管理员权限修改 Windows 可选功能。
- 是否接受安装过程中可能要求重启。
- 是否接受安装 Ubuntu Linux 发行版。
- 是否接受 WSL2 使用额外磁盘空间和运行时内存。

建议 Agent 对用户说明：

> mini-note 在 Windows 上需要 WSL2 才能稳定运行。安装 WSL2 需要管理员 PowerShell，可能需要重启。安装后一般不会长期占用大量 CPU，但导入/解析文件时会占用一定内存、CPU 和磁盘。是否继续？

用户明确同意后再执行安装步骤。

## 3. 前置条件检查

在 PowerShell 中检查 Windows 版本：

```powershell
winver
```

需要满足以下条件：

- Windows 11，或 Windows 10 version 2004 及以上（Build 19041 及以上）。
- BIOS/UEFI 已开启虚拟化。
- 用户能使用管理员 PowerShell。
- 机器有足够磁盘空间。建议至少预留 10GB；如果要导入大量文件，按文件总量额外预留 3 倍以上空间。

如果安装 WSL2 时提示虚拟化未启用，需要用户进入 BIOS/UEFI 开启 Intel VT-x / AMD-V，Agent 不应尝试自行修改 BIOS。

## 4. 安装 WSL2

在管理员 PowerShell 中执行：

```powershell
wsl --install -d Ubuntu
```

如果公司网络或 Microsoft Store 下载受限，可按提示使用：

```powershell
wsl --install --web-download -d Ubuntu
```

安装完成后按系统提示重启。重启后打开 Ubuntu，创建 Linux 用户名和密码。

检查 WSL 状态：

```powershell
wsl --status
wsl --list --verbose
```

目标状态是 Ubuntu 使用 WSL version 2。

## 5. 在 WSL2 中安装 mini-note

打开 Ubuntu 终端，执行：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone https://github.com/jiggersong/mini-note.git ~/mini-note
cd ~/mini-note
./install.sh
./verify.sh --quick
```

如果用户已经有项目源码，可以把仓库放到 WSL 文件系统内：

```bash
mkdir -p ~/code
cd ~/code
git clone <repo-url> mini-note
cd mini-note
./install.sh
```

不要优先放到 `/mnt/c/Users/<name>/...` 下运行。Linux 命令行项目放在 `/home/<linux-user>/...` 内，文件 IO 性能和权限语义更稳定。

## 6. 配置 OpenClaw / WorkBuddy

Agent 侧应使用 WSL shell 执行命令，而不是 Windows 原生 PowerShell/CMD。

推荐配置：

```bash
MINI_NOTE_WORKSPACE=/home/<linux-user>/mini-note
```

常用命令：

```bash
cd "$MINI_NOTE_WORKSPACE"
./run.sh health --json
./run.sh ingest --file /home/<linux-user>/Documents/example.pdf --owner user-default --scope shared --json
./import.sh /home/<linux-user>/Documents/notes --owner user-default
./run.sh query --question "要查询的问题" --scope shared --json
```

如果 Agent 只能从 Windows 侧发起命令，可以通过 `wsl` 包一层：

```powershell
wsl -d Ubuntu -- bash -lc "cd ~/mini-note && ./run.sh health --json"
wsl -d Ubuntu -- bash -lc "cd ~/mini-note && ./import.sh ~/Documents/notes --owner user-default"
```

注意：Windows 路径需要转换为 WSL 路径，例如：

```text
C:\Users\Alice\Documents\notes
```

在 WSL 中对应：

```text
/mnt/c/Users/Alice/Documents/notes
```

大量导入时，建议先把资料复制到 WSL 文件系统内再导入：

```bash
mkdir -p ~/Documents/imports
cp -r /mnt/c/Users/Alice/Documents/notes ~/Documents/imports/notes
cd ~/mini-note
./import.sh ~/Documents/imports/notes --owner user-default
```

## 7. 资源成本评估

### 7.1 一次性成本

安装 WSL2 的成本主要是：

- 需要管理员权限。
- 可能需要重启。
- 会安装 Ubuntu 发行版。
- 会创建 WSL2 虚拟磁盘文件。
- 首次安装依赖需要联网下载 Python 包。

对普通用户来说，操作复杂度属于“中等”：比安装一个普通 Windows 应用复杂，但比完整虚拟机或双系统轻。

### 7.2 磁盘成本

WSL2 使用虚拟硬盘（VHD）保存 Linux 文件系统，并会随使用增长。mini-note 自身和 Python 依赖通常不是主要成本，主要成本来自导入资料：

- WSL2 + Ubuntu 基础环境：通常数 GB 级。
- Python venv 和依赖：通常数百 MB 到 1GB 级，取决于依赖 wheel。
- mini-note 数据：批量导入会产生 inbox 副本、archive 副本、extracted 文本、SQLite 索引和快照。保守估算应按原始文件体积的 3 倍以上预留。

建议：

- 首次使用至少预留 10GB。
- 导入大目录前使用 `./import.sh` 默认磁盘预检。
- 如果资料目录很大，先让用户确认是否继续。

### 7.3 内存和 CPU 成本

WSL2 是轻量虚拟化环境，通常比完整虚拟机资源成本低；但它仍然会在运行时占用内存和 CPU。

实际影响：

- 空闲时一般不会明显拖慢电脑。
- 执行 `pip install`、PDF/Office 解析、大量文件导入、SQLite 重建索引时会短时间占用 CPU 和内存。
- 低配机器（8GB 内存或机械硬盘）上，批量导入大目录可能让系统变慢。

不建议在以下机器上让 Agent 自动安装并大量导入：

- 8GB 内存以下。
- C 盘可用空间不足 10GB。
- 用户正在运行重型 IDE、浏览器多标签、Docker Desktop 或本地大模型。
- 公司电脑禁用虚拟化或不允许安装 Windows 可选功能。

### 7.4 限制 WSL2 资源占用

如果用户担心卡顿，可在 Windows 用户目录创建或编辑：

```text
C:\Users\<WindowsUser>\.wslconfig
```

示例：

```ini
[wsl2]
memory=4GB
processors=2
swap=2GB
```

保存后在 PowerShell 执行：

```powershell
wsl --shutdown
```

再次打开 Ubuntu 后生效。低配机器可把 `memory` 设为 `2GB`，但导入大型 PDF/Office 文件时更容易失败或变慢；较稳妥的默认值是 `4GB`。

## 8. 日常维护命令

关闭 WSL，释放运行时资源：

```powershell
wsl --shutdown
```

查看已安装发行版：

```powershell
wsl --list --verbose
```

进入 Ubuntu：

```powershell
wsl -d Ubuntu
```

在 WSL 中查看磁盘空间：

```bash
df -h
du -sh ~/mini-note
```

## 9. 不建议原生 Windows 运行的原因

当前若不使用 WSL2，需要额外开发和验证：

- PowerShell 版 `install.ps1`、`run.ps1`、`import.ps1`。
- Windows 原生路径和环境变量处理。
- 跨平台 PID 存活检测，建议改用 `psutil`。
- Windows CI 覆盖 symlink、SQLite FTS5、PDF/Office 解析、tar 恢复和锁清理。
- Windows 版 Skill 命令映射。

在这些工作完成前，不应承诺原生 Windows 可稳定安装使用。

## 10. [References]

- [Install WSL | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/install)
- [Basic commands for WSL | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)
- [Working across Windows and Linux file systems | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
- [Advanced settings configuration in WSL | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
- [How to manage WSL disk space | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/disk-space)

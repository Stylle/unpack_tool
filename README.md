# Unpack Tool

用于批量生成、下载并向 qBittorrent 或 Transmission 推送 `.torrent` 文件的 Windows 桌面工具。

完整安装、配置和操作步骤见 [USER_GUIDE.md](USER_GUIDE.md)。

## 主要能力

- qBittorrent 4.x / 5.x 使用统一的 Web API 用户名、密码登录，不需要 API Key。
- Transmission RPC 自动处理 Session ID 更新。
- 支持普通链接和 `子路径|链接` 两种 links 格式。
- 每处理一个种子就保存状态；程序重启后可继续下载或直接推送。
- 随机下载间隔会验证并持久化。
- 默认保留本地种子文件。
- 可选择让推送到 qBittorrent 或 Transmission 的种子保持暂停状态。
- 默认开启下载完成后自动推送，也可以在任务页关闭。

## 使用

1. 将链接模板 `.txt` 放入程序旁的 `links` 文件夹。
2. 在“任务”页填写 Website、Passkey 和下载器能够访问的做种路径。
3. 生成任务并下载种子；默认下载完成后会自动推送。
4. 在“下载器与设置”页配置 qBittorrent 或 Transmission，测试连接。
5. 回到“任务”页开始推送。

做种路径是下载器所在设备看到的路径。例如下载器运行在 NAS 上时，应填写 NAS 路径，而不是当前电脑的路径。

## links 格式

普通路径：

```text
{website}/download.php?id=100&passkey={passkey}
```

指定子路径：

```text
电影合集/第一部|{website}/download.php?id=100&passkey={passkey}
```

仍兼容旧模板中的 `https://website` 和 `yourpasskey`。

## 开发

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
python torrent_manager.py
```

构建发布包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1 -Version 1.1.4
```

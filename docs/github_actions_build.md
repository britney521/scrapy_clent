# GitHub Actions 打包 Windows 客户端 EXE

## 文件说明

- `.github/workflows/build-windows-client.yml`：GitHub Actions 工作流
- `requirements-client.txt`：客户端打包依赖
- `client_app.spec`：PyInstaller 打包配置
- `scripts/build_client.py`：本地/CI 打包脚本

## 云端打包

1. 推送代码到 GitHub。
2. 打开仓库 `Actions`。
3. 选择 `Build Windows Client EXE`。
4. 点击 `Run workflow`。
5. 等待完成后，在 Artifacts 下载：

```text
crawler-client-windows.zip
```

解压后运行：

```text
crawler-client/crawler-client.exe
```

## 默认服务端地址

当前默认 API：

```text
http://101.34.208.172:5006/api
```

如需临时切换，在 Windows PowerShell 运行：

```powershell
$env:CRAWLER_API_BASE="http://127.0.0.1:8000/api"
.\crawler-client.exe
```

## 浏览器路径

Windows 默认 Chrome 路径：

```text
C:\Program Files\Google\Chrome\Application\chrome.exe
```

如需指定：

```powershell
$env:CRAWLER_BROWSER_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
.\crawler-client.exe
```

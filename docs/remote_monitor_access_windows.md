# PaperWatcher 监控网页远程访问说明

本文记录从 Windows PowerShell 通过 SSH 隧道访问 PaperWatcher 监控网页的方式。

## 为什么不能直接访问公网地址

监控网页服务当前只监听在服务器本机的 `8080` 端口，并不等于这个端口已经对公网开放。

因此：

- `http://127.0.0.1:8080/` 只有在本机或通过 SSH 隧道时可访问。
- `http://<ECS公网IP>:8080/` 只有在云安全组、系统防火墙、服务绑定方式都允许时才可访问。
- 当前推荐方式是 SSH 本地端口转发，不需要放开公网端口。

## PowerShell 操作步骤

### 1. 打开 PowerShell

在 Windows 上打开 PowerShell。

### 2. 建立 SSH 隧道

把本机 `8080` 端口转发到 ECS 服务器的 `127.0.0.1:8080`：

```powershell
ssh -L 8080:127.0.0.1:8080 paperdev@116.62.178.66
//ssh -N -L 8080:127.0.0.1:8080 paperdev@<ECS公网IP>
```

如果你本机的 `8080` 已经被占用，可以改成别的本地端口，例如 `18080`：

```powershell
ssh -N -L 18080:127.0.0.1:8080 paperdev@<ECS公网IP>
```

如果你需要指定私钥，可以加上 `-i`：

```powershell
ssh -i C:\path\to\your_key -N -L 8080:127.0.0.1:8080 paperdev@<ECS公网IP>
```

### 3. 打开浏览器访问

隧道建立后，在浏览器里打开：

```text
http://127.0.0.1:8080/?token=kYtHBDEdYA5oHRqiPb6t-TpWzi3HfhRv
```

如果你使用的是其他本地端口，比如 `18080`，就访问：

```text
http://127.0.0.1:18080/?token=kYtHBDEdYA5oHRqiPb6t-TpWzi3HfhRv
```

## 看到什么算正常

- 页面标题是 `PaperWatcher Monitor`
- 顶部能看到 `Refresh` 和 `Auto refresh`
- `Events`、`Sources`、`Health`、`Users`、`Reviews`、`Candidates`、`Conference Pages` 这些页签可切换

## 常见问题

### 1. 页面打不开

先检查 SSH 隧道窗口是否还在运行。隧道窗口关闭后，本地 `127.0.0.1:8080` 就会失效。

### 2. 端口占用

如果本机 `8080` 已经被其他程序占用，把本地端口换成 `18080`、`28080` 之类即可。

### 3. token 不对

页面 URL 里的 `token` 必须和服务器上的 `logs/monitor_web.token` 一致。

### 4. 需要停止访问

在 PowerShell 的 SSH 窗口里按 `Ctrl+C` 即可断开隧道。

## 当前服务状态

当前后台监控和网页监控都已启动，网页服务由 systemd 管理，并读取：

```text
/home/paperdev/文献与会议追踪系统/logs/monitor_web.token
```


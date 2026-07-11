# -*- coding: utf-8 -*-
"""
种子下载推送工具
===============================
功能：
  1. 支持 qBittorrent 和 Transmission 下载器，测试连接
  2. 读取 links/ 文件夹中的 .txt 文件（种子链接模板）
  3. 替换占位符 {website} {passkey} 生成真实下载链接
  4. 下载 .torrent 文件（带随机延时，默认 5~60 秒）
  5. 推送种子文件到下载器（保存路径 = 做种路径）
  6. 状态跟踪：待下载 → 已下载 → 已推送

依赖：Python 3.10+, tkinter (内置), requests
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import time
import random
import threading
import base64
from datetime import datetime

try:
    import requests
except ImportError:
    messagebox.showerror("缺少依赖", "需要安装 requests 库，请运行：pip install requests")
    sys.exit(1)

def _get_base_dir():
    """获取程序基础目录
    - 开发模式：脚本所在目录
    - PyInstaller 打包后：exe 所在目录
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
LINKS_DIR = os.path.join(BASE_DIR, "links")
TORRENTS_DIR = os.path.join(BASE_DIR, "torrents")

MIN_DELAY = 5.0
MAX_DELAY = 60.0
TIMEOUT = 30


class QBClient:
    def __init__(self, host, port, username="", password=""):
        self.base_url = f"http://{host}:{port}"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.logged_in = False

    def test_connection(self):
        try:
            r = self.session.get(f"{self.base_url}/api/v2/app/webapiVersion", timeout=TIMEOUT)
            if r.status_code == 200:
                if self.username:
                    r2 = self.session.post(f"{self.base_url}/api/v2/auth/login",
                                           data={"username": self.username, "password": self.password},
                                           timeout=TIMEOUT)
                    if r2.status_code == 200 and "Ok" in r2.text:
                        self.logged_in = True
                        return True, f"QBittorrent v{r.text.strip()} 连接成功"
                    else:
                        return False, f"登录失败: {r2.text.strip()}"
                else:
                    self.logged_in = True
                    return True, f"QBittorrent v{r.text.strip()} 连接成功"
            elif r.status_code == 403:
                return False, "访问被拒绝，请检查 IP 白名单"
            else:
                return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, f"无法连接到 {self.base_url}"
        except Exception as e:
            return False, str(e)

    def add_torrent_file(self, torrent_path, save_path):
        if not self.logged_in:
            ok, msg = self.test_connection()
            if not ok:
                return False, msg
        try:
            with open(torrent_path, "rb") as f:
                files = {"torrents": (os.path.basename(torrent_path), f, "application/x-bittorrent")}
                data = {"savepath": save_path, "autoTMM": "false"}
                r = self.session.post(f"{self.base_url}/api/v2/torrents/add",
                                      files=files, data=data, timeout=TIMEOUT)
            if r.status_code == 200 and r.text.strip() == "Ok.":
                return True, "推送成功"
            else:
                return False, r.text.strip() or f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)


class QB5Client:
    """qBittorrent v5 API密钥认证客户端（含诊断）"""

    def __init__(self, host, port, api_key=""):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.api_key = api_key
        self.session = requests.Session()
        self.logged_in = True
        self.diagnostic_log = []

    def _all_urls(self):
        urls = [self.base_url]
        if self.host == "127.0.0.1":
            urls.append(f"http://localhost:{self.port}")
        elif self.host == "localhost":
            urls.append(f"http://127.0.0.1:{self.port}")
        seen = []
        for u in urls:
            if u not in seen:
                seen.append(u)
        return seen

    def test_connection(self):
        self.diagnostic_log = []
        alive = False
        for base_url in self._all_urls():
            try:
                r = self.session.get(base_url, timeout=TIMEOUT)
                self.diagnostic_log.append(f"  GET {base_url} HTTP {r.status_code}")
                if r.status_code < 500:
                    alive = True
            except Exception as e:
                self.diagnostic_log.append(f"  GET {base_url} -> {e}")
        if not alive:
            diag = "\n".join(self.diagnostic_log)
            return False, f"QB WebUI 无响应! 诊断:\n{diag}\n\n请确认端口 {self.port} 正确, WebUI 已启用"
        for base_url in self._all_urls():
            try:
                headers = {"X-API-Key": self.api_key, "Referer": base_url + "/"}
                r = self.session.get(f"{base_url}/api/v2/app/version", headers=headers, timeout=TIMEOUT)
                text = r.text.strip()
                self.diagnostic_log.append(f"  Header GET {base_url}/api/v2/app/version -> HTTP {r.status_code} body=[{text}]")
                if r.status_code == 200:
                    return True, f"QBittorrent v5 {text} 连接成功（API密钥）"
            except Exception as e:
                self.diagnostic_log.append(f"  Header GET -> 异常: {e}")
            try:
                r = self.session.get(f"{base_url}/api/v2/app/version?api_key={self.api_key}", timeout=TIMEOUT)
                text = r.text.strip()
                self.diagnostic_log.append(f"  Query GET {base_url}/api/v2/app/version?api_key=... -> HTTP {r.status_code} body=[{text}]")
                if r.status_code == 200:
                    return True, f"QBittorrent v5 {text} 连接成功（URL参数）"
            except Exception as e:
                self.diagnostic_log.append(f"  Query GET -> 异常: {e}")
        diag = "\n".join(self.diagnostic_log)
        return False, f"API密钥认证失败! 诊断:\n{diag}\n\n请确认:\n  1. QB v5 WebUI 中已生成 API 密钥\n  2. 输入框中的密钥无多余空格\n  3. 地址和端口正确"

    def add_torrent_file(self, torrent_path, save_path):
        try:
            self.session.get(f"{self.base_url}/api/v2/app/version", headers={"X-API-Key": self.api_key, "Referer": self.base_url + "/"}, timeout=TIMEOUT)
        except Exception:
            pass
        try:
            with open(torrent_path, "rb") as f:
                files = {"torrents": (os.path.basename(torrent_path), f, "application/x-bittorrent")}
                data = {"savepath": save_path, "autoTMM": "false"}
                r = self.session.post(f"{self.base_url}/api/v2/torrents/add", files=files, data=data, headers={"X-API-Key": self.api_key, "Referer": self.base_url + "/"}, timeout=TIMEOUT)
            text = r.text.strip()
            if r.status_code == 200:
                if text == "" or text == "Ok." or text == "Ok" or '"success_count":1' in text:
                    return True, "推送成功"
            if r.status_code == 409:
                return False, "添加失败，请检查种子是否存在."
            if text:
                return False, f"QB返回: {text} (HTTP {r.status_code})"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, f"推送异常: {str(e)}"

class TRClient:
    def __init__(self, host, port, username="", password=""):
        self.rpc_url = f"http://{host}:{port}/transmission/rpc"
        self.auth = (username, password) if username else None
        self.session = requests.Session()
        self.session_id = None
        if self.auth:
            self.session.auth = self.auth

    def _ensure_session(self):
        try:
            r = self.session.get(self.rpc_url, timeout=TIMEOUT)
            if "X-Transmission-Session-Id" in r.headers:
                self.session_id = r.headers["X-Transmission-Session-Id"]
                return True
            return False
        except Exception:
            return False

    def _rpc(self, method, args=None):
        if not self.session_id:
            if not self._ensure_session():
                return {"success": False, "msg": "无法获取 Session ID"}
        headers = {"X-Transmission-Session-Id": self.session_id}
        payload = {"method": method}
        if args:
            payload["arguments"] = args
        try:
            r = self.session.post(self.rpc_url, json=payload, headers=headers, timeout=TIMEOUT)
            if r.status_code == 409:
                if self._ensure_session():
                    headers["X-Transmission-Session-Id"] = self.session_id
                    r = self.session.post(self.rpc_url, json=payload, headers=headers, timeout=TIMEOUT)
                else:
                    return {"success": False, "msg": "Session ID 过期"}
            data = r.json()
            ok = data.get("result") == "success"
            return {"success": ok, "data": data, "msg": data.get("result", "unknown")}
        except Exception as e:
            return {"success": False, "msg": str(e)}

    def test_connection(self):
        result = self._rpc("session-get")
        if result.get("success"):
            ver = result["data"].get("arguments", {}).get("version", "?")
            return True, f"Transmission {ver} 连接成功"
        else:
            return False, result.get("msg", "未知错误")

    def add_torrent_file(self, torrent_path, save_path):
        try:
            with open(torrent_path, "rb") as f:
                metainfo = base64.b64encode(f.read()).decode("utf-8")
            result = self._rpc("torrent-add", {"metainfo": metainfo, "download-dir": save_path})
            if result.get("success"):
                return True, "推送成功"
            else:
                msg = result.get("msg", "未知错误")
                # 检查是否已经是重复添加
                if "duplicate" in msg.lower() or "already" in msg.lower():
                    return True, "种子已存在"
                return False, msg
        except Exception as e:
            return False, str(e)


class TorrentManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("种子下载推送工具 - Torrent Manager")
        self.root.geometry("1080x780")
        self.root.minsize(960, 650)

        self.torrent_items = []
        self.downloader_client = None
        self.current_link_file = ""
        self.downloading = False
        self.pushing = False

        # 暂停/停止控制
        self.download_paused = threading.Event()
        self.push_paused = threading.Event()
        self.download_stopped = False
        self.push_stopped = False

        os.makedirs(LINKS_DIR, exist_ok=True)
        os.makedirs(TORRENTS_DIR, exist_ok=True)

        self.setup_ui()
        self.scan_link_files()
        self.log("程序启动，请配置下载器参数并选择链接文件")

    # ── UI ──
    def setup_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # 下载器配置
        f1 = ttk.LabelFrame(main, text="下载器配置", padding=8)
        f1.pack(fill=tk.X, pady=(0, 8))

        r0 = ttk.Frame(f1); r0.pack(fill=tk.X, pady=2)
        ttk.Label(r0, text="类型：").pack(side=tk.LEFT)
        self.cmb_dl = ttk.Combobox(r0, values=["qBittorrent", "qBittorrent v5 (API密钥)", "Transmission"], state="readonly", width=22)
        self.cmb_dl.set("qBittorrent")
        self.cmb_dl.pack(side=tk.LEFT, padx=(0, 16))
        self.cmb_dl.bind("<<ComboboxSelected>>", lambda e: self._dl_type_changed())

        ttk.Label(r0, text="地址：").pack(side=tk.LEFT)
        self.entry_host = ttk.Entry(r0, width=18)
        self.entry_host.insert(0, "127.0.0.1")
        self.entry_host.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(r0, text="端口：").pack(side=tk.LEFT)
        self.entry_port = ttk.Entry(r0, width=7)
        self.entry_port.insert(0, "8080")
        self.entry_port.pack(side=tk.LEFT, padx=(0, 16))

        self.frm_creds = ttk.Frame(r0)
        self.frm_creds.pack(side=tk.LEFT)
        self.lbl_user = ttk.Label(self.frm_creds, text="用户名：")
        self.lbl_user.grid(row=0, column=0, padx=(0, 4))
        self.entry_user = ttk.Entry(self.frm_creds, width=14)
        self.entry_user.grid(row=0, column=1, padx=(0, 8))
        self.lbl_auth = ttk.Label(self.frm_creds, text="密码：")
        self.lbl_auth.grid(row=0, column=2, padx=(0, 4))
        self.entry_pass = ttk.Entry(self.frm_creds, width=14, show="*")
        self.entry_pass.grid(row=0, column=3, padx=(0, 16))

        self.btn_test = ttk.Button(r0, text="测试连接", command=self.on_test)
        self.btn_test.pack(side=tk.LEFT)
        self.lbl_conn = ttk.Label(r0, text="")
        self.lbl_conn.pack(side=tk.LEFT, padx=(8, 0))

        # 链接文件
        f2 = ttk.LabelFrame(main, text="链接文件与替换", padding=8)
        f2.pack(fill=tk.X, pady=(0, 8))

        r1 = ttk.Frame(f2); r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="文件：").pack(side=tk.LEFT)
        self.cmb_file = ttk.Combobox(r1, state="readonly", width=28)
        self.cmb_file.pack(side=tk.LEFT, padx=(0, 16))
        self.cmb_file.bind("<<ComboboxSelected>>", lambda e: self._file_selected())
        ttk.Button(r1, text="刷新", command=self.scan_link_files, width=8).pack(side=tk.LEFT)

        r2 = ttk.Frame(f2); r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="Website：").pack(side=tk.LEFT)
        self.e_web = ttk.Entry(r2, width=40)
        self.e_web.insert(0, "https://example.com")
        self.e_web.pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(r2, text="Passkey：").pack(side=tk.LEFT)
        self.e_pk = ttk.Entry(r2, width=40)
        self.e_pk.pack(side=tk.LEFT, padx=(0, 16))

        r3 = ttk.Frame(f2); r3.pack(fill=tk.X, pady=2)
        ttk.Label(r3, text="做种路径：").pack(side=tk.LEFT)
        self.e_seed = ttk.Entry(r3, width=60)
        self.e_seed.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(r3, text="浏览", command=self.on_browse, width=8).pack(side=tk.LEFT, padx=(0, 16))
        self.btn_replace = ttk.Button(r3, text="替换生成", command=self.on_replace, width=12)
        self.btn_replace.pack(side=tk.LEFT)

        # 种子列表
        f3 = ttk.LabelFrame(main, text="种子列表", padding=4)
        f3.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        cols = ("#", "种子链接 / 文件名", "状态")
        self.tree = ttk.Treeview(f3, columns=cols, show="headings", height=12, selectmode="extended")
        self.tree.heading("#", text="#")
        self.tree.heading("种子链接 / 文件名", text="种子链接 / 文件名")
        self.tree.heading("状态", text="状态")
        self.tree.column("#", width=50, anchor=tk.CENTER)
        self.tree.column("种子链接 / 文件名", width=550)
        self.tree.column("状态", width=120, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(f3, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(f3, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        f3.grid_rowconfigure(0, weight=1)
        f3.grid_columnconfigure(0, weight=1)

        # 操作按钮
        fb = ttk.Frame(main); fb.pack(fill=tk.X, pady=(0, 8))
        self.btn_dl = ttk.Button(fb, text="开始下载", command=self.on_download, width=12)
        self.btn_dl.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_pause_dl = ttk.Button(fb, text="暂停下载", command=self.on_pause_download, width=10)
        self.btn_pause_dl.pack(side=tk.LEFT, padx=(0, 12))
        self.btn_push = ttk.Button(fb, text="开始推送", command=self.on_push, width=12)
        self.btn_push.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_pause_push = ttk.Button(fb, text="暂停推送", command=self.on_pause_push, width=10)
        self.btn_pause_push.pack(side=tk.LEFT, padx=(0, 12))
        self.cb_del = tk.BooleanVar(value=True)
        ttk.Checkbutton(fb, text="推送后删除本地文件", variable=self.cb_del).pack(side=tk.LEFT, padx=(12, 0))
        self.prog = ttk.Progressbar(fb, mode="indeterminate", length=180)
        self.prog.pack(side=tk.LEFT, padx=(0, 12))
        self.lbl_stat = ttk.Label(fb, text="就绪")
        self.lbl_stat.pack(side=tk.LEFT)

        # 日志
        fl = ttk.LabelFrame(main, text="日志", padding=4)
        fl.pack(fill=tk.X, pady=(0, 4))
        self.txt_log = tk.Text(fl, height=10, wrap=tk.WORD, state=tk.DISABLED,
                               bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        sv = ttk.Scrollbar(fl, orient=tk.VERTICAL, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sv.set)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sv.pack(side=tk.RIGHT, fill=tk.Y)

        self._sync_buttons()

    def _dl_type_changed(self):
        tp = self.cmb_dl.get()
        if tp == "qBittorrent v5 (API密钥)":
            self.entry_port.delete(0, tk.END)
            self.entry_port.insert(0, "8080")
            self.lbl_user.grid_remove()
            self.entry_user.grid_remove()
            self.lbl_auth.configure(text="API密钥：")
            self.entry_pass.configure(show="")
            self.entry_pass.delete(0, tk.END)
        elif tp == "Transmission":
            self.entry_port.delete(0, tk.END)
            self.entry_port.insert(0, "9091")
            self.lbl_user.grid()
            self.entry_user.grid()
            self.lbl_auth.configure(text="密码：")
            self.entry_pass.configure(show="*")
        else:
            self.entry_port.delete(0, tk.END)
            self.entry_port.insert(0, "8080")
            self.lbl_user.grid()
            self.entry_user.grid()
            self.lbl_auth.configure(text="密码：")
            self.entry_pass.configure(show="*")
        self.lbl_conn.configure(text="")
        self.downloader_client = None

    def _file_selected(self):
        idx = self.cmb_file.current()
        if idx >= 0 and hasattr(self.cmb_file, "_files"):
            fl = self.cmb_file._files
            if idx < len(fl):
                self.current_link_file = fl[idx]

    def _sync_buttons(self):
        has_list = len(self.torrent_items) > 0
        dl_running = self.downloading
        push_running = self.pushing
        has_torrent_files = False
        if os.path.exists(TORRENTS_DIR):
            has_torrent_files = any(f.endswith(".torrent") for f in os.listdir(TORRENTS_DIR))

        self.btn_dl.configure(state=tk.NORMAL if (has_list and not dl_running) else tk.DISABLED)
        self.btn_push.configure(state=tk.NORMAL if (has_torrent_files and not push_running and self.downloader_client) else tk.DISABLED)
        self.btn_replace.configure(state=tk.NORMAL if not self.downloading else tk.DISABLED)
        self.btn_pause_dl.configure(state=tk.NORMAL if dl_running else tk.DISABLED)
        self.btn_pause_push.configure(state=tk.NORMAL if push_running else tk.DISABLED)

    # ── 暂停下载 ──
    def on_pause_download(self):
        if self.download_paused.is_set():
            self.download_paused.clear()
            self.btn_pause_dl.configure(text="暂停下载")
            self.log("继续下载任务")
        else:
            self.download_paused.set()
            self.btn_pause_dl.configure(text="继续下载")
            self.log("已暂停下载任务")

    # ── 暂停推送 ──
    def on_pause_push(self):
        if self.push_paused.is_set():
            self.push_paused.clear()
            self.btn_pause_push.configure(text="暂停推送")
            self.log("继续推送任务")
        else:
            self.push_paused.set()
            self.btn_pause_push.configure(text="继续推送")
            self.log("已暂停推送任务")

    # ── 日志 ──
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, f"[{ts}] {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)
        self.root.update_idletasks()

    def err(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, f"[{ts}] ❌ {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)
        self.root.update_idletasks()

    # ── 扫描链接文件 ──
    def scan_link_files(self):
        os.makedirs(LINKS_DIR, exist_ok=True)
        files = sorted([f for f in os.listdir(LINKS_DIR) if f.endswith(".txt")])
        paths = [os.path.join(LINKS_DIR, f) for f in files]
        if not files:
            self.cmb_file["values"] = ["（无文件）"]
            self.cmb_file.set("")
            self.cmb_file._files = []
            self.log("links/ 中无 .txt 文件")
            return
        self.cmb_file["values"] = files
        self.cmb_file.set(files[0])
        self.cmb_file._files = paths
        self.current_link_file = paths[0]

    # ── 浏览路径 ──
    def on_browse(self):
        p = filedialog.askdirectory(title="选择做种路径")
        if p:
            self.e_seed.delete(0, tk.END); self.e_seed.insert(0, p)
            self.log(f"做种路径: {p}")

    # ── 测试连接 ──
    def on_test(self):
        host = self.entry_host.get().strip()
        port = self.entry_port.get().strip()
        user = self.entry_user.get().strip()
        pwd = self.entry_pass.get().strip()
        tp = self.cmb_dl.get()
        if not host or not port or not port.isdigit():
            messagebox.showwarning("提示", "请输入正确的地址和端口"); return
        self.lbl_conn.configure(text="⏳ 测试中...", foreground="gray")
        self.btn_test.configure(state=tk.DISABLED)
        self.log(f"测试 {tp} {host}:{port}...")

        def run():
            if tp == "qBittorrent v5 (API\u5bc6\u94a5)":
                c = QB5Client(host, port, pwd)
            elif tp == "qBittorrent":
                c = QBClient(host, port, user, pwd)
            else:
                c = TRClient(host, port, user, pwd)
            ok, msg = c.test_connection()
            self.root.after(0, lambda: self._test_result(ok, msg, c))

        threading.Thread(target=run, daemon=True).start()

    def _test_result(self, ok, msg, client):
        self.btn_test.configure(state=tk.NORMAL)
        if ok:
            self.lbl_conn.configure(text="✅ 已连接", foreground="green")
            self.downloader_client = client
            self.log(f"✅ {msg}")
        else:
            self.lbl_conn.configure(text="❌ 失败", foreground="red")
            self.downloader_client = None
            self.err(msg)
        self._sync_buttons()

    # ── 替换生成 ──
    def on_replace(self):
        web = self.e_web.get().strip()
        pk = self.e_pk.get().strip()
        seed = self.e_seed.get().strip()
        if not web or web == "https://example.com":
            messagebox.showwarning("提示", "请输入 Website"); return
        if not pk:
            messagebox.showwarning("提示", "请输入 Passkey"); return
        if not seed:
            messagebox.showwarning("提示", "请选择做种路径"); return
        if not self.current_link_file or not os.path.exists(self.current_link_file):
            messagebox.showwarning("提示", "请先选择链接文件"); return

        try:
            with open(self.current_link_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败: {e}"); return

        items = []
        seen = set()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            url = line.replace("{website}", web).replace("{passkey}", pk)
            if url in seen:
                continue
            seen.add(url)
            items.append({"url": url, "filepath": "", "status": "待下载"})

        if not items:
            messagebox.showwarning("提示", "文件中无有效链接"); return

        self.torrent_items = items
        self._refresh_tree()
        self.log(f"替换完成，共 {len(items)} 个种子")
        self._sync_buttons()

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, item in enumerate(self.torrent_items, 1):
            disp = item["url"] if len(item["url"]) <= 60 else item["url"][:57] + "..."
            self.tree.insert("", tk.END, values=(str(i), disp, item["status"]),
                             tags=(item["status"],))
        self.tree.tag_configure("待下载", foreground="#666666")
        self.tree.tag_configure("已下载", foreground="#2e7d32")
        self.tree.tag_configure("已推送", foreground="#1565c0")

    # ── 开始下载 ──
    def on_download(self):
        if self.downloading:
            return
        pend = [i for i in self.torrent_items if i["status"] == "待下载"]
        if not pend:
            messagebox.showinfo("提示", "没有待下载的种子"); return

        self.downloading = True
        self.prog.start(15)
        self.lbl_stat.configure(text="下载中...")
        self._sync_buttons()
        self.log(f"开始下载 {len(pend)} 个种子（延时 {MIN_DELAY}~{MAX_DELAY}s）")

        def run():
            self.download_stopped = False
            self.download_paused.clear()
            ok_n, fail_n = 0, 0
            for i, item in enumerate(self.torrent_items):
                if item["status"] != "待下载":
                    continue

                # 检查是否被完全停止
                if self.download_stopped:
                    self.root.after(0, lambda: self.log("下载任务已停止"))
                    break

                url = item["url"]
                fname = f"torr_{int(time.time())}_{random.randint(1000,9999)}.torrent"
                fpath = os.path.join(TORRENTS_DIR, fname)

                self.root.after(0, lambda u=url: self.log(f"下载 [{i+1}]: {u[:60]}..."))

                # 检查暂停状态，非忙等待
                if self.download_paused.is_set():
                    self.root.after(0, lambda: self.log("下载已暂停，等待继续..."))
                while self.download_paused.is_set():
                    if self.download_stopped:
                        break
                    time.sleep(1.0)

                if self.download_stopped:
                    self.root.after(0, lambda: self.log("下载任务已停止"))
                    break

                try:
                    r = requests.get(url, timeout=TIMEOUT)
                    r.raise_for_status()
                    with open(fpath, "wb") as f:
                        f.write(r.content)
                    item["filepath"] = fpath
                    item["status"] = "已下载"
                    ok_n += 1
                    self.root.after(0, lambda fn=fname: self.log(f"✅ 已下载: {fn}"))
                except Exception as e:
                    fail_n += 1
                    self.root.after(0, lambda e=e: self.err(f"下载失败: {str(e)[:80]}"))

                # 检查是否停止
                if self.download_stopped:
                    self.root.after(0, lambda: self.log("下载任务已停止"))
                    break

                # 非最后一项则延时
                remaining = [it for it in self.torrent_items if it["status"] == "待下载"]
                if remaining and not self.download_paused.is_set():
                    d = random.uniform(MIN_DELAY, MAX_DELAY)
                    self.root.after(0, lambda d=d: self.log(f"等待 {d:.1f}s..."))
                    for _ in range(int(d / 0.5)):
                        if self.download_stopped or self.download_paused.is_set():
                            break
                        time.sleep(0.5)
                elif remaining:
                    while self.download_paused.is_set() and not self.download_stopped:
                        time.sleep(1.0)

            self.root.after(0, lambda: self._dl_done(ok_n, fail_n))

        threading.Thread(target=run, daemon=True).start()

    def _dl_done(self, ok, fail):
        self.downloading = False
        self.prog.stop()
        self.lbl_stat.configure(text="下载完成")
        self.log(f"🎉 下载完成: 成功 {ok}, 失败 {fail}")
        self._refresh_tree()
        self._sync_buttons()
        # 重置暂停状态
        self.download_paused.clear()
        self.btn_pause_dl.configure(text="暂停下载")

    # ── 开始推送 ──
    def on_push(self):
        if self.pushing:
            return
        if not self.downloader_client:
            messagebox.showwarning("提示", "请先连接下载器"); return

        # 扫描 torrents/ 文件夹
        torrent_files = []
        if os.path.exists(TORRENTS_DIR):
            for fname in sorted(os.listdir(TORRENTS_DIR)):
                if fname.endswith(".torrent"):
                    torrent_files.append(os.path.join(TORRENTS_DIR, fname))

        if not torrent_files:
            messagebox.showinfo("提示", "torrents/ 文件夹中没有种子文件")
            return

        self.pushing = True
        self.prog.start(15)
        self.lbl_stat.configure(text="推送中...")
        self._sync_buttons()
        seed = self.e_seed.get().strip()
        self.log(f"扫描到 {len(torrent_files)} 个种子文件，开始推送...")

        def run():
            self.push_stopped = False
            self.push_paused.clear()
            ok_n, fail_n = 0, 0
            pushed_names = []
            delete_flag = self.cb_del.get()

            for filepath in torrent_files:
                if self.push_stopped:
                    self.root.after(0, lambda: self.log("推送任务已停止"))
                    break

                if self.push_paused.is_set():
                    self.root.after(0, lambda: self.log("推送已暂停，等待继续..."))
                while self.push_paused.is_set():
                    if self.push_stopped:
                        break
                    time.sleep(1.0)

                if self.push_stopped:
                    break

                if not os.path.exists(filepath):
                    self.root.after(0, lambda fn=os.path.basename(filepath): self.err(f"文件不存在，跳过: {fn}"))
                    fail_n += 1
                    continue

                self.root.after(0, lambda fn=os.path.basename(filepath): self.log(f"推送: {fn}"))

                try:
                    ok, msg = self.downloader_client.add_torrent_file(filepath, seed)
                    if ok:
                        ok_n += 1
                        pushed_names.append(os.path.basename(filepath))
                        self.root.after(0, lambda fn=os.path.basename(filepath): self.log(f"✅ 已推送: {fn}"))

                        if delete_flag:
                            try:
                                os.remove(filepath)
                                self.root.after(0, lambda fn=os.path.basename(filepath): self.log(f"已删除本地缓存文件: {fn}"))
                            except OSError as e:
                                self.root.after(0, lambda fn=os.path.basename(filepath): self.err(f"删除文件失败 [{fn}]: {e}"))
                    else:
                        fail_n += 1
                        self.root.after(0, lambda fn=os.path.basename(filepath), m=msg: self.err(f"推送失败 [{fn}]: {m}"))
                except Exception as e:
                    fail_n += 1
                    self.root.after(0, lambda e=e: self.err(f"推送异常: {str(e)}"))

            self.root.after(0, lambda: self._push_done(ok_n, fail_n, pushed_names))

        threading.Thread(target=run, daemon=True).start()

    def _push_done(self, ok, fail, names):
        self.pushing = False
        self.prog.stop()
        self.lbl_stat.configure(text="推送完成")
        self.log(f"推送完成: 成功 {ok}, 失败 {fail}")
        self._sync_buttons()
        self.push_paused.clear()
        self.btn_pause_push.configure(text="暂停推送")
        if ok > 0:
            msg = f"✅ 成功推送 {ok} 个种子\n保存路径: {self.e_seed.get().strip()}\n\n"
            for n in names:
                msg += f"  • {n} ✅\n"
            if fail > 0:
                msg += f"\n❌ 失败: {fail} 个"
            messagebox.showinfo("推送结果", msg)



def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    style = ttk.Style()
    for t in ("vista", "clam", "default"):
        if t in style.theme_names():
            style.theme_use(t); break

    app = TorrentManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

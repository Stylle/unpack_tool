import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .clients import QBittorrentClient, TransmissionClient
from .links import LinkFormatError, join_download_path, parse_link_file
from .models import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_PENDING, STATUS_PUSHED
from .paths import AppPaths
from .service import TorrentService
from .storage import StateStore


APP_BG = "#f4f6f8"
PANEL_BG = "#ffffff"
TEXT = "#17212b"
MUTED = "#66727f"
ACCENT = "#1976d2"
SUCCESS = "#16835b"
ERROR = "#c43d4b"


class TorrentManagerApp:
    def __init__(self, root: tk.Tk, base_dir: str | None = None):
        self.root = root
        self.paths = AppPaths.create(base_dir)
        self.store = StateStore(self.paths.database)
        self.service = TorrentService(self.store, self.paths.torrents)
        self.items = self.store.reconcile(self.paths.torrents)
        self.client = None
        self.running_task = ""
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.link_files: list[Path] = []

        self._configure_window()
        self._create_variables()
        self._create_styles()
        self._build_ui()
        self._load_config()
        self._scan_link_files()
        self._refresh_items()
        self._set_status("就绪", MUTED)
        self._log(f"已恢复 {len(self.items)} 条种子记录")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self) -> None:
        self.root.title("Unpack Tool - 种子下载与推送")
        self.root.geometry("1180x800")
        self.root.minsize(980, 680)
        self.root.configure(bg=APP_BG)
        try:
            self.root.tk.call("tk", "scaling", 1.15)
        except tk.TclError:
            pass

    def _create_variables(self) -> None:
        self.downloader_var = tk.StringVar(value="qBittorrent")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="8080")
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.link_file_var = tk.StringVar()
        self.website_var = tk.StringVar(value="https://example.com")
        self.passkey_var = tk.StringVar()
        self.seed_path_var = tk.StringVar()
        self.min_delay_var = tk.StringVar(value="5")
        self.max_delay_var = tk.StringVar(value="60")
        self.delete_after_push_var = tk.BooleanVar(value=False)
        self.connection_var = tk.StringVar(value="未连接")
        self.summary_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.path_preview_var = tk.StringVar(value="目标路径将在这里显示")

    def _create_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("App.TFrame", background=APP_BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure("Panel.TLabelframe", background=PANEL_BG, borderwidth=1)
        style.configure("Panel.TLabelframe.Label", background=PANEL_BG, foreground=TEXT)
        style.configure("Title.TLabel", background=APP_BG, foreground=TEXT, font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtle.TLabel", background=APP_BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL_BG, foreground=MUTED)
        style.configure("Accent.TButton", padding=(14, 7), font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame", padding=(18, 14))
        shell.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="Unpack Tool", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text="种子下载与推送", style="Subtle.TLabel").pack(side=tk.LEFT, padx=(12, 0), pady=(7, 0))
        self.connection_label = ttk.Label(header, textvariable=self.connection_var, style="Subtle.TLabel")
        self.connection_label.pack(side=tk.RIGHT, pady=(7, 0))

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        task_tab = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 10, 0, 0))
        settings_tab = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 10, 0, 0))
        self.notebook.add(task_tab, text="任务")
        self.notebook.add(settings_tab, text="下载器与设置")
        self._build_task_tab(task_tab)
        self._build_settings_tab(settings_tab)

        footer = ttk.Frame(shell, style="App.TFrame")
        footer.pack(fill=tk.X, pady=(10, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=180)
        self.progress.pack(side=tk.LEFT)
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Subtle.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(footer, textvariable=self.summary_var, style="Subtle.TLabel").pack(side=tk.RIGHT)

    def _build_task_tab(self, parent: ttk.Frame) -> None:
        source = ttk.LabelFrame(parent, text="链接与路径", style="Panel.TLabelframe", padding=12)
        source.pack(fill=tk.X, pady=(0, 10))
        source.columnconfigure(1, weight=1)
        source.columnconfigure(4, weight=1)

        self._label(source, "链接文件", 0, 0)
        self.link_combo = ttk.Combobox(source, textvariable=self.link_file_var, state="readonly", width=34)
        self.link_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=4)
        self.link_combo.bind("<<ComboboxSelected>>", lambda _event: self._select_link_file())
        ttk.Button(source, text="刷新", command=self._scan_link_files).grid(row=0, column=2, padx=(0, 18), pady=4)
        self._label(source, "做种路径", 0, 3)
        ttk.Entry(source, textvariable=self.seed_path_var).grid(row=0, column=4, sticky="ew", padx=8, pady=4)
        ttk.Button(source, text="浏览", command=self._browse_seed_path).grid(row=0, column=5, pady=4)

        self._label(source, "Website", 1, 0)
        ttk.Entry(source, textvariable=self.website_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 18), pady=4)
        self._label(source, "Passkey", 1, 3)
        ttk.Entry(source, textvariable=self.passkey_var, show="*").grid(row=1, column=4, columnspan=2, sticky="ew", padx=(8, 0), pady=4)

        self._label(source, "随机间隔", 2, 0)
        delay = ttk.Frame(source, style="Panel.TFrame")
        delay.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        ttk.Entry(delay, textvariable=self.min_delay_var, width=7).pack(side=tk.LEFT)
        ttk.Label(delay, text=" 至 ", style="Panel.TLabel").pack(side=tk.LEFT)
        ttk.Entry(delay, textvariable=self.max_delay_var, width=7).pack(side=tk.LEFT)
        ttk.Label(delay, text=" 秒", style="Panel.TLabel").pack(side=tk.LEFT)
        ttk.Button(source, text="生成任务", style="Accent.TButton", command=self._generate_tasks).grid(row=2, column=4, sticky="e", padx=8, pady=(6, 2))
        ttk.Button(source, text="保存设置", command=lambda: self._save_config(True)).grid(row=2, column=5, sticky="e", pady=(6, 2))

        table_frame = ttk.Frame(parent, style="Panel.TFrame", padding=1)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("number", "name", "path", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("number", text="#")
        self.tree.heading("name", text="链接 / 种子文件")
        self.tree.heading("path", text="目标子路径")
        self.tree.heading("status", text="状态")
        self.tree.column("number", width=48, minwidth=48, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=560, minwidth=300)
        self.tree.column("path", width=260, minwidth=140)
        self.tree.column("status", width=100, minwidth=90, anchor=tk.CENTER, stretch=False)
        self.tree.tag_configure(STATUS_PENDING, foreground=MUTED)
        self.tree.tag_configure(STATUS_DOWNLOADED, foreground=SUCCESS)
        self.tree.tag_configure(STATUS_PUSHED, foreground=ACCENT)
        self.tree.tag_configure(STATUS_FAILED, foreground=ERROR)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_path_preview())
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        controls = ttk.Frame(parent, style="App.TFrame")
        controls.pack(fill=tk.X, pady=(10, 0))
        self.download_button = ttk.Button(controls, text="开始下载", style="Accent.TButton", command=self._start_download)
        self.download_button.pack(side=tk.LEFT)
        self.push_button = ttk.Button(controls, text="开始推送", style="Accent.TButton", command=self._start_push)
        self.push_button.pack(side=tk.LEFT, padx=(8, 0))
        self.pause_button = ttk.Button(controls, text="暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(controls, text="选中项重新推送", command=self._reset_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(controls, text="推送后删除本地种子", variable=self.delete_after_push_var, command=self._save_config).pack(side=tk.RIGHT)

        preview = ttk.Label(parent, textvariable=self.path_preview_var, style="Subtle.TLabel")
        preview.pack(fill=tk.X, pady=(8, 0))

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="下载器连接", style="Panel.TLabelframe", padding=16)
        panel.pack(fill=tk.X, pady=(0, 10))
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(3, weight=1)
        self._label(panel, "类型", 0, 0)
        downloader = ttk.Combobox(panel, textvariable=self.downloader_var, values=("qBittorrent", "Transmission"), state="readonly")
        downloader.grid(row=0, column=1, sticky="ew", padx=(8, 24), pady=6)
        downloader.bind("<<ComboboxSelected>>", lambda _event: self._downloader_changed())
        self._label(panel, "地址", 0, 2)
        ttk.Entry(panel, textvariable=self.host_var).grid(row=0, column=3, sticky="ew", padx=8, pady=6)

        self._label(panel, "端口", 1, 0)
        ttk.Entry(panel, textvariable=self.port_var).grid(row=1, column=1, sticky="ew", padx=(8, 24), pady=6)
        self._label(panel, "用户名", 1, 2)
        ttk.Entry(panel, textvariable=self.username_var).grid(row=1, column=3, sticky="ew", padx=8, pady=6)
        self._label(panel, "密码", 2, 0)
        ttk.Entry(panel, textvariable=self.password_var, show="*").grid(row=2, column=1, sticky="ew", padx=(8, 24), pady=6)

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.test_button = ttk.Button(actions, text="测试连接", style="Accent.TButton", command=self._test_connection)
        self.test_button.pack(side=tk.LEFT)

        log_panel = ttk.LabelFrame(parent, text="运行日志", style="Panel.TLabelframe", padding=8)
        log_panel.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(
            log_panel,
            height=15,
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.FLAT,
            bg="#161b22",
            fg="#d8dee9",
            insertbackground="#ffffff",
            font=("Consolas", 10),
            padx=10,
            pady=8,
        )
        log_scrollbar = ttk.Scrollbar(log_panel, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    @staticmethod
    def _label(parent, text: str, row: int, column: int) -> None:
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=4)

    def _load_config(self) -> None:
        get = self.store.get_config
        saved_type = get("downloader_type", "qBittorrent")
        if saved_type.startswith("qBittorrent"):
            saved_type = "qBittorrent"
        self.downloader_var.set(saved_type)
        self.host_var.set(get("host", "127.0.0.1"))
        self.port_var.set(get("port", "8080" if saved_type == "qBittorrent" else "9091"))
        self.username_var.set(get("username"))
        self.password_var.set(get("password"))
        self.website_var.set(get("website", "https://example.com"))
        self.passkey_var.set(get("passkey"))
        self.seed_path_var.set(get("seed_path"))
        self.min_delay_var.set(get("min_delay", "5"))
        self.max_delay_var.set(get("max_delay", "60"))
        self.delete_after_push_var.set(get("delete_after_push", "0") == "1")
        self.link_file_var.set(Path(get("link_file", "")).name)

    def _save_config(self, notify: bool = False) -> bool:
        try:
            minimum, maximum = self._delay_values()
        except ValueError as exc:
            messagebox.showwarning("随机间隔无效", str(exc))
            return False
        self.store.save_config(
            {
                "downloader_type": self.downloader_var.get(),
                "host": self.host_var.get().strip(),
                "port": self.port_var.get().strip(),
                "username": self.username_var.get().strip(),
                "password": self.password_var.get(),
                "website": self.website_var.get().strip(),
                "passkey": self.passkey_var.get().strip(),
                "seed_path": self.seed_path_var.get().strip(),
                "min_delay": str(minimum),
                "max_delay": str(maximum),
                "delete_after_push": "1" if self.delete_after_push_var.get() else "0",
                "link_file": str(self._selected_link_path() or ""),
            }
        )
        if notify:
            self._log("设置已保存")
        return True

    def _delay_values(self) -> tuple[float, float]:
        try:
            minimum = float(self.min_delay_var.get())
            maximum = float(self.max_delay_var.get())
        except ValueError as exc:
            raise ValueError("随机间隔必须填写数字") from exc
        if minimum < 0 or maximum < minimum:
            raise ValueError("随机间隔需满足 0 <= 最小值 <= 最大值")
        return minimum, maximum

    def _scan_link_files(self) -> None:
        selected = self.link_file_var.get()
        self.link_files = sorted(self.paths.links.glob("*.txt"), key=lambda path: path.name)
        names = [path.name for path in self.link_files]
        self.link_combo["values"] = names
        if selected in names:
            self.link_file_var.set(selected)
        elif names:
            self.link_file_var.set(names[0])
        else:
            self.link_file_var.set("")

    def _selected_link_path(self) -> Path | None:
        name = self.link_file_var.get()
        return next((path for path in self.link_files if path.name == name), None)

    def _select_link_file(self) -> None:
        self._save_config()

    def _browse_seed_path(self) -> None:
        selected = filedialog.askdirectory(title="选择做种数据所在目录")
        if selected:
            self.seed_path_var.set(selected)
            self._save_config()
            self._update_path_preview()

    def _generate_tasks(self) -> None:
        path = self._selected_link_path()
        if not path:
            messagebox.showwarning("缺少链接文件", "请在 links 文件夹中放入 .txt 文件并刷新")
            return
        website = self.website_var.get().strip()
        passkey = self.passkey_var.get().strip()
        if not website or website == "https://example.com" or not passkey:
            messagebox.showwarning("配置不完整", "请填写 Website 和 Passkey")
            return
        if not self.seed_path_var.get().strip():
            messagebox.showwarning("配置不完整", "请填写下载器可访问的做种路径")
            return
        try:
            items = parse_link_file(path, website, passkey)
        except (OSError, LinkFormatError) as exc:
            messagebox.showerror("链接解析失败", str(exc))
            return
        if not items:
            messagebox.showwarning("没有链接", "链接文件中没有有效记录")
            return
        if self.items and not messagebox.askyesno("替换任务", "生成新任务会替换当前列表，是否继续？"):
            return
        self.items = items
        self.store.replace_items(self.items)
        self._save_config()
        self._refresh_items()
        self._log(f"已从 {path.name} 生成 {len(items)} 条任务")

    def _create_client(self):
        client_class = QBittorrentClient if self.downloader_var.get() == "qBittorrent" else TransmissionClient
        return client_class(
            self.host_var.get(),
            self.port_var.get(),
            self.username_var.get(),
            self.password_var.get(),
        )

    def _downloader_changed(self) -> None:
        self.client = None
        self.connection_var.set("未连接")
        self.port_var.set("8080" if self.downloader_var.get() == "qBittorrent" else "9091")
        self._save_config()
        self._sync_buttons()

    def _test_connection(self) -> None:
        if self.running_task:
            return
        self.test_button.configure(state=tk.DISABLED)
        self.connection_var.set("连接中...")
        candidate = self._create_client()

        def work():
            result = candidate.test_connection()
            self.root.after(0, lambda: self._connection_done(candidate, *result))

        threading.Thread(target=work, daemon=True).start()

    def _connection_done(self, client, ok: bool, message: str) -> None:
        self.test_button.configure(state=tk.NORMAL)
        if ok:
            self.client = client
            self.connection_var.set("已连接")
            self.connection_label.configure(foreground=SUCCESS)
            self._save_config()
            self._log(message)
        else:
            self.client = None
            self.connection_var.set("连接失败")
            self.connection_label.configure(foreground=ERROR)
            self._log(message, error=True)
            messagebox.showerror("连接失败", message)
        self._sync_buttons()

    def _start_download(self) -> None:
        if self.running_task:
            return
        try:
            minimum, maximum = self._delay_values()
        except ValueError as exc:
            messagebox.showwarning("随机间隔无效", str(exc))
            return
        pending = [item for item in self.items if item.status in {STATUS_PENDING, STATUS_FAILED} and not item.filepath]
        if not pending:
            messagebox.showinfo("没有待下载项", "当前任务没有需要下载的种子")
            return
        self._save_config()
        self._begin_task("download", f"正在下载 {len(pending)} 个种子")

        def work():
            result = self.service.download_pending(
                self.items, minimum, maximum, self.pause_event, self.stop_event,
                self._thread_log, self._thread_refresh,
            )
            self.root.after(0, lambda: self._task_done("下载", *result))

        threading.Thread(target=work, daemon=True).start()

    def _start_push(self) -> None:
        if self.running_task:
            return
        if not self.client:
            self.client = self._create_client()
        save_path = self.seed_path_var.get().strip()
        if not save_path:
            messagebox.showwarning("缺少路径", "请填写下载器可访问的做种路径")
            return
        candidates = [item for item in self.items if item.filepath and Path(item.filepath).exists() and item.status != STATUS_PUSHED]
        if not candidates:
            messagebox.showinfo("没有待推送项", "没有已下载且尚未推送的种子")
            return
        self._save_config()
        delete_after_push = self.delete_after_push_var.get()
        self._begin_task("push", f"正在推送 {len(candidates)} 个种子")

        def work():
            result = self.service.push_downloaded(
                self.items, self.client, save_path, delete_after_push,
                self.pause_event, self.stop_event, self._thread_log, self._thread_refresh,
            )
            self.root.after(0, lambda: self._task_done("推送", *result))

        threading.Thread(target=work, daemon=True).start()

    def _begin_task(self, name: str, status: str) -> None:
        self.running_task = name
        self.stop_event.clear()
        self.pause_event.clear()
        self.progress.start(12)
        self.pause_button.configure(text="暂停", state=tk.NORMAL)
        self._set_status(status, ACCENT)
        self._sync_buttons()

    def _toggle_pause(self) -> None:
        if not self.running_task:
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_button.configure(text="暂停")
            self._set_status("任务继续", ACCENT)
        else:
            self.pause_event.set()
            self.pause_button.configure(text="继续")
            self._set_status("已暂停", MUTED)

    def _task_done(self, label: str, success: int, failure: int) -> None:
        self.running_task = ""
        self.pause_event.clear()
        self.progress.stop()
        self.pause_button.configure(text="暂停", state=tk.DISABLED)
        self._refresh_items()
        self._sync_buttons()
        color = SUCCESS if failure == 0 else ERROR
        self._set_status(f"{label}完成：成功 {success}，失败 {failure}", color)
        self._log(f"{label}完成：成功 {success}，失败 {failure}", error=failure > 0)

    def _reset_selected(self) -> None:
        indexes = [int(item_id) for item_id in self.tree.selection()]
        if not indexes:
            messagebox.showinfo("未选择", "请选择需要重新推送的记录")
            return
        changed = 0
        for index in indexes:
            item = self.items[index]
            if item.filepath and Path(item.filepath).exists():
                item.status = STATUS_DOWNLOADED
                item.error = ""
                self.store.save_item(item)
                changed += 1
        self._refresh_items()
        self._log(f"已将 {changed} 条记录标记为待推送")

    def _refresh_items(self) -> None:
        selection = set(self.tree.selection()) if hasattr(self, "tree") else set()
        for row in self.tree.get_children():
            self.tree.delete(row)
        for index, item in enumerate(self.items):
            name = Path(item.filepath).name if item.filepath else item.url
            if len(name) > 90:
                name = name[:87] + "..."
            self.tree.insert("", tk.END, iid=str(index), values=(index + 1, name, item.sub_path or "根目录", item.status), tags=(item.status,))
        for item_id in selection:
            if self.tree.exists(item_id):
                self.tree.selection_add(item_id)
        counts = {status: sum(item.status == status for item in self.items) for status in (STATUS_PENDING, STATUS_DOWNLOADED, STATUS_PUSHED, STATUS_FAILED)}
        self.summary_var.set(
            f"共 {len(self.items)} | 待下载 {counts[STATUS_PENDING]} | 已下载 {counts[STATUS_DOWNLOADED]} | 已推送 {counts[STATUS_PUSHED]} | 失败 {counts[STATUS_FAILED]}"
        )
        self._sync_buttons()

    def _update_path_preview(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.path_preview_var.set("选择一条任务可预览推送路径")
            return
        item = self.items[int(selected[0])]
        try:
            target = join_download_path(self.seed_path_var.get(), item.sub_path)
            self.path_preview_var.set(f"推送目标：{target}")
        except LinkFormatError as exc:
            self.path_preview_var.set(f"路径无效：{exc}")

    def _sync_buttons(self) -> None:
        busy = bool(self.running_task)
        pending = any(item.status in {STATUS_PENDING, STATUS_FAILED} and not item.filepath for item in self.items)
        pushable = any(item.filepath and Path(item.filepath).exists() and item.status != STATUS_PUSHED for item in self.items)
        self.download_button.configure(state=tk.NORMAL if pending and not busy else tk.DISABLED)
        self.push_button.configure(state=tk.NORMAL if pushable and not busy else tk.DISABLED)

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=color)

    def _thread_log(self, message: str, error: bool = False) -> None:
        self.root.after(0, lambda: self._log(message, error))

    def _thread_refresh(self) -> None:
        self.root.after(0, self._refresh_items)

    def _log(self, message: str, error: bool = False) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {'错误: ' if error else ''}{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._save_config()
        if self.running_task:
            self.stop_event.set()
        self.root.destroy()


def main() -> None:
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    TorrentManagerApp(root)
    root.mainloop()

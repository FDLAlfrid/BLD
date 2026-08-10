#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站视频下载工具 - GUI版 (sv-ttk 主题)
版本: 2.3
功能: 支持URL/BV/AV号输入，自动WBI签名，多P选择，音视频分离下载并合并
主题: 支持亮色/暗色切换 (Windows 11 风格)
特色: 批量下载，下载历史，并发下载，右键粘贴，自动打开文件夹
"""

import re
import json
import time
import hashlib
import subprocess
import os
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox, filedialog, simpledialog, Menu
import webbrowser

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

__version__ = "2.3"

# ---------- 配置 ----------
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
}
HISTORY_FILE = "history.json"

# ---------- 工具函数（复用原代码） ----------
def get_session_with_retry():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

def parse_input(text):
    text = text.strip()
    if text.startswith("http"):
        bv_match = re.search(r"BV[a-zA-Z0-9]+", text)
        if bv_match:
            return "bvid", bv_match.group()
        av_match = re.search(r"av(\d+)", text, re.I)
        if av_match:
            return "aid", av_match.group(1)
        raise ValueError("无法从 URL 中识别 BV 或 AV 号")
    if text.upper().startswith("BV"):
        if re.match(r"^BV[a-zA-Z0-9]+$", text):
            return "bvid", text
        else:
            raise ValueError("BV 号格式不正确")
    if text.lower().startswith("av"):
        num = text[2:]
        if num.isdigit():
            return "aid", num
    if text.isdigit():
        return "aid", text
    raise ValueError("无法识别的输入格式，请提供 URL、BV 或 AV 号")

def load_cookies_from_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    elif isinstance(data, list):
        cookies = {}
        for item in data:
            if "name" in item and "value" in item:
                cookies[item["name"]] = item["value"]
        return cookies
    else:
        raise ValueError("不支持的 cookies 格式")

def get_cookies_from_browser_auto():
    browsers = ["chrome", "edge", "firefox", "brave", "opera"]
    for browser in browsers:
        try:
            import browser_cookie3
            browser_func = getattr(browser_cookie3, browser.lower())
            cj = browser_func(domain_name=".bilibili.com")
            cookies = {c.name: c.value for c in cj}
            if cookies:
                return cookies, browser
        except Exception:
            continue
    return None, None

def get_wbi_keys(session, cookies=None):
    url = "https://api.bilibili.com/x/web-interface/nav"
    resp = session.get(url, headers=HEADERS, cookies=cookies)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise Exception(f"获取 nav 失败: {data['message']}")
    wbi_img = data["data"]["wbi_img"]
    img_url = wbi_img["img_url"]
    sub_url = wbi_img["sub_url"]
    img_key = img_url.split("/")[-1].split(".")[0]
    sub_key = sub_url.split("/")[-1].split(".")[0]
    return img_key, sub_key

def get_mixin_key(img_key, sub_key):
    mixin_key = img_key + sub_key
    return mixin_key[:32]

def sign_params(params, mixin_key):
    params = params.copy()
    params["wts"] = int(time.time())
    sorted_keys = sorted(params.keys())
    sorted_params = {k: params[k] for k in sorted_keys}
    query = "&".join([f"{k}={v}" for k, v in sorted_params.items()])
    sign_str = query + mixin_key
    w_rid = hashlib.md5(sign_str.encode()).hexdigest()
    params["w_rid"] = w_rid
    return params

def get_video_info(session, bvid=None, aid=None, cookies=None):
    if bvid:
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
    elif aid:
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"aid": aid}
    else:
        raise ValueError("必须提供 bvid 或 aid")
    resp = session.get(url, params=params, headers=HEADERS, cookies=cookies)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise Exception(f"获取视频信息失败: {data['message']}")
    return data["data"]

def get_playurl(session, bvid, cid, qn=80, fnval=4048, cookies=None):
    img_key, sub_key = get_wbi_keys(session, cookies)
    mixin_key = get_mixin_key(img_key, sub_key)
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": qn,
        "fnval": fnval,
        "fnver": 0,
        "fourk": 1,
        "otype": "json",
    }
    signed_params = sign_params(params, mixin_key)
    url = "https://api.bilibili.com/x/player/playurl"
    resp = session.get(url, params=signed_params, headers=HEADERS, cookies=cookies)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise Exception(f"获取播放地址失败: {data['message']}")
    dash = data["data"]["dash"]
    video_info = dash["video"][0]
    audio_info = dash["audio"][0]
    return video_info["baseUrl"], audio_info["baseUrl"]

def download_file(session, url, filename, progress_callback=None):
    headers = HEADERS.copy()
    headers["Referer"] = "https://www.bilibili.com/"
    resp = session.get(url, headers=headers, stream=True)
    resp.raise_for_status()
    total_size = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size:
                    percent = (downloaded / total_size) * 100
                    progress_callback(percent, downloaded, total_size)
    return filename

def merge_with_ffmpeg(video_path, audio_path, output_path):
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        raise FileNotFoundError("视频或音频文件不存在")
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        "-y",
        output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except FileNotFoundError:
        return False, "未找到 ffmpeg，请安装并添加到 PATH"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ---------- GUI 应用程序 ----------
class BiliDownloaderApp:
    def __init__(self, root):
        self.root = root
        root.title(f"B站视频下载器 v{__version__}")
        root.geometry("800x700")
        root.minsize(750, 650)

        # 主题变量
        self.current_theme = tk.StringVar(value="light")

        # 变量
        self.input_var = tk.StringVar()
        self.qn_var = tk.IntVar(value=80)
        self.output_var = tk.StringVar()
        self.cookies_file_var = tk.StringVar()
        self.no_merge_var = tk.BooleanVar(value=False)
        self.skip_history_var = tk.BooleanVar(value=True)
        self.open_folder_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.batch_mode_var = tk.BooleanVar(value=False)

        # 下载状态
        self.download_params = None
        self.is_downloading = False
        self.history = load_history()

        # 创建菜单栏
        self.create_menu()

        # 创建界面
        self.create_widgets()

        # 绑定右键菜单
        self.setup_context_menu()

        # 应用主题
        self.apply_theme("light")

    def create_menu(self):
        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        # 主题菜单
        theme_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="主题", menu=theme_menu)
        theme_menu.add_command(label="亮色", command=lambda: self.apply_theme("light"))
        theme_menu.add_command(label="暗色", command=lambda: self.apply_theme("dark"))

        # 帮助菜单
        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="关于", command=self.show_about)
        help_menu.add_command(label="查看历史", command=self.show_history)

    def apply_theme(self, theme):
        """应用亮色或暗色主题"""
        if HAS_SV_TTK:
            sv_ttk.set_theme(theme)
            self.current_theme.set(theme)
            self.adjust_log_colors(theme)
        else:
            bg = "#f0f0f0" if theme == "light" else "#2d2d2d"
            fg = "black" if theme == "light" else "white"
            self.root.tk_setPalette(background=bg, foreground=fg)

    def adjust_log_colors(self, theme):
        if theme == "dark":
            bg = "#1e1e1e"
            fg = "#d4d4d4"
            insert = "white"
        else:
            bg = "white"
            fg = "black"
            insert = "black"
        self.log_text.config(bg=bg, fg=fg, insertbackground=insert)

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---------- 输入区域 ----------
        input_frame = ttk.LabelFrame(main_frame, text="视频输入", padding="5")
        input_frame.pack(fill=tk.X, pady=5)

        ttk.Checkbutton(input_frame, text="批量模式 (每行一个)", variable=self.batch_mode_var).grid(row=0, column=0, sticky=tk.W, padx=5)

        self.entry = tk.Text(input_frame, height=3 if self.batch_mode_var.get() else 1, font=("微软雅黑", 9))
        self.entry.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=5)
        self.batch_mode_var.trace('w', self.toggle_batch_mode)

        ttk.Button(input_frame, text="解析并下载", command=self.start_download).grid(row=1, column=2, padx=5, sticky=tk.N)

        # ---------- 选项区域 ----------
        opt_frame = ttk.LabelFrame(main_frame, text="下载选项", padding="5")
        opt_frame.pack(fill=tk.X, pady=5)

        ttk.Label(opt_frame, text="清晰度:").grid(row=0, column=0, sticky=tk.W, padx=5)
        qn_combo = ttk.Combobox(opt_frame, textvariable=self.qn_var, values=[64, 80, 112, 116], state="readonly", width=10)
        qn_combo.grid(row=0, column=1, sticky=tk.W, padx=5)
        qn_combo.set(80)
        ttk.Label(opt_frame, text="(64=720p, 80=1080p, 112=高码率, 116=4K)").grid(row=0, column=2, sticky=tk.W, padx=5)

        ttk.Label(opt_frame, text="输出文件名(不含后缀):").grid(row=1, column=0, sticky=tk.W, padx=5)
        entry_out = ttk.Entry(opt_frame, textvariable=self.output_var, width=30)
        entry_out.grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Label(opt_frame, text="(留空则自动使用视频标题)").grid(row=1, column=2, sticky=tk.W, padx=5)

        ttk.Label(opt_frame, text="Cookies文件:").grid(row=2, column=0, sticky=tk.W, padx=5)
        entry_cookie = ttk.Entry(opt_frame, textvariable=self.cookies_file_var, width=30)
        entry_cookie.grid(row=2, column=1, sticky=tk.W, padx=5)
        ttk.Button(opt_frame, text="浏览", command=self.browse_cookie).grid(row=2, column=2, sticky=tk.W, padx=5)

        ttk.Checkbutton(opt_frame, text="不合并(分别下载音视频)", variable=self.no_merge_var).grid(row=3, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="跳过已下载 (历史)", variable=self.skip_history_var).grid(row=3, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="完成后打开文件夹", variable=self.open_folder_var).grid(row=3, column=2, sticky=tk.W, padx=5)

        # ---------- 日志区域 ----------
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD, state=tk.DISABLED, font=("微软雅黑", 9))
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ---------- 状态栏 ----------
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=2)

        self.progress = ttk.Progressbar(status_frame, mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var)
        self.status_label.pack(side=tk.RIGHT, padx=5)

        input_frame.columnconfigure(0, weight=1)
        input_frame.columnconfigure(1, weight=1)
        opt_frame.columnconfigure(0, weight=0)
        opt_frame.columnconfigure(1, weight=0)
        opt_frame.columnconfigure(2, weight=1)

    def toggle_batch_mode(self, *args):
        if self.batch_mode_var.get():
            self.entry.config(height=4)
        else:
            self.entry.config(height=1)

    def setup_context_menu(self):
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="粘贴", command=self.paste_from_clipboard)
        self.entry.bind("<Button-3>", self.show_context_menu)

    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def paste_from_clipboard(self):
        try:
            clipboard_text = self.root.clipboard_get()
            self.entry.delete(1.0, tk.END)
            self.entry.insert(1.0, clipboard_text)
        except tk.TclError:
            pass

    def browse_cookie(self):
        filename = filedialog.askopenfilename(title="选择 Cookies 文件", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if filename:
            self.cookies_file_var.set(filename)

    def log(self, msg, level="INFO"):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{level}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def update_progress(self, percent, downloaded, total):
        self.progress['value'] = percent
        self.status_var.set(f"下载中 {percent:.1f}% ({downloaded}/{total})")
        self.root.update_idletasks()

    def start_download(self):
        if self.is_downloading:
            messagebox.showinfo("提示", "正在下载中，请稍候")
            return

        input_text = self.entry.get(1.0, tk.END).strip()
        if not input_text:
            messagebox.showerror("错误", "请输入视频 URL、BV 或 AV 号")
            return

        if self.batch_mode_var.get():
            items = [line.strip() for line in input_text.splitlines() if line.strip()]
        else:
            items = [input_text]

        if not items:
            messagebox.showerror("错误", "未检测到有效输入")
            return

        self.log("========== 开始批量下载 ==========")
        self.progress['value'] = 0
        self.status_var.set("准备下载...")

        self.is_downloading = True
        thread = threading.Thread(target=self.batch_download_worker, args=(items,), daemon=True)
        thread.start()

    def batch_download_worker(self, items):
        total = len(items)
        for idx, raw_input in enumerate(items, 1):
            self.log(f"\n--- 开始处理第 {idx}/{total} 个: {raw_input} ---")
            try:
                self.download_single(raw_input)
            except Exception as e:
                self.log(f"处理失败: {e}", "ERROR")
        self.log("\n========== 全部处理完成 ==========")
        self.status_var.set("完成")
        self.is_downloading = False

    def download_single(self, input_text):
        try:
            id_type, id_val = parse_input(input_text)
            self.log(f"识别为: {id_type}={id_val}")
        except ValueError as e:
            self.log(f"解析失败: {e}", "ERROR")
            return

        # 检查历史
        if self.skip_history_var.get():
            for h in self.history:
                if h.get("bvid") == id_val and id_type == "bvid":
                    self.log(f"跳过已下载: {h.get('title', id_val)}", "INFO")
                    return
                elif h.get("aid") == id_val and id_type == "aid":
                    self.log(f"跳过已下载: {h.get('title', id_val)}", "INFO")
                    return

        cookies = self.get_cookies()
        if cookies is None:
            self.log("未能获取 Cookies，将使用无 Cookie 模式（可能受限）", "WARNING")

        session = get_session_with_retry()

        try:
            video_info = get_video_info(session,
                                        bvid=id_val if id_type=="bvid" else None,
                                        aid=id_val if id_type=="aid" else None,
                                        cookies=cookies)
        except Exception as e:
            self.log(f"获取视频信息失败: {e}", "ERROR")
            return

        title = video_info.get("title", "无标题")
        pages = video_info.get("pages", [])
        if not pages:
            self.log("未找到分 P", "ERROR")
            return

        self.log(f"视频标题: {title}")
        self.log(f"共 {len(pages)} 个分 P")
        desc = video_info.get("desc", "无简介")
        self.log(f"简介: {desc[:100]}...")

        if len(pages) == 1:
            choice = 0
        else:
            p_list = [f"{i+1}. {p.get('part', f'P{i+1}')} (cid={p['cid']})" for i, p in enumerate(pages)]
            choice_str = simpledialog.askstring("选择分 P",
                                                f"请选择要下载的分 P (输入序号 1-{len(pages)}):\n" + "\n".join(p_list))
            if not choice_str:
                self.log("用户取消选择", "WARNING")
                return
            try:
                choice = int(choice_str) - 1
                if not (0 <= choice < len(pages)):
                    raise ValueError
            except:
                self.log("输入无效，默认为第1P", "WARNING")
                choice = 0

        selected_page = pages[choice]
        cid = selected_page["cid"]
        bvid = video_info["bvid"]
        self.log(f"选中: {selected_page.get('part', f'P{choice+1}')} (cid={cid})")

        self.download_params = {
            'session': session,
            'bvid': bvid,
            'cid': cid,
            'title': title,
            'choice': choice,
            'cookies': cookies,
            'selected_page': selected_page
        }

        self.download_single_worker()

        # 记录历史
        if not self.no_merge_var.get():
            history_entry = {
                "bvid": bvid,
                "aid": video_info.get("aid"),
                "title": title,
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            self.history = [h for h in self.history if h.get("bvid") != bvid]
            self.history.append(history_entry)
            save_history(self.history)
            self.log("已记录下载历史")

    def get_cookies(self):
        cookies = None
        if self.cookies_file_var.get():
            try:
                cookies = load_cookies_from_file(self.cookies_file_var.get())
                self.log(f"已加载 Cookies: 文件 {self.cookies_file_var.get()}")
                return cookies
            except Exception as e:
                self.log(f"加载 cookies 文件失败: {e}", "ERROR")
                messagebox.showerror("错误", f"加载 cookies 失败:\n{e}")
                return None
        else:
            default_file = "cookies.json"
            if os.path.exists(default_file):
                try:
                    cookies = load_cookies_from_file(default_file)
                    self.log(f"已加载 Cookies: 本地文件 {default_file}")
                    return cookies
                except Exception as e:
                    self.log(f"加载本地 cookies.json 失败: {e}", "WARNING")
            self.log("尝试从浏览器获取 Cookies...")
            try:
                cookies, browser = get_cookies_from_browser_auto()
                if cookies:
                    self.log(f"已从 {browser} 获取 Cookies")
                    return cookies
                else:
                    self.log("未能从任何浏览器获取 Cookies，将使用无 Cookie 模式（可能受限）", "WARNING")
            except Exception as e:
                self.log(f"浏览器获取失败: {e}", "WARNING")
        return None

    def download_single_worker(self):
        params = self.download_params
        session = params['session']
        bvid = params['bvid']
        cid = params['cid']
        title = params['title']
        choice = params['choice']
        cookies = params['cookies']

        try:
            video_url, audio_url = get_playurl(session, bvid, cid, qn=self.qn_var.get(), cookies=cookies)
            self.log("获取播放地址成功")
        except Exception as e:
            self.log(f"获取播放地址失败: {e}", "ERROR")
            self.root.after(0, lambda: messagebox.showerror("错误", f"获取播放地址失败:\n{e}"))
            self.status_var.set("错误")
            return

        base_name = self.output_var.get().strip()
        if not base_name:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            if not safe_title:
                safe_title = f"video_{bvid}"
            base_name = f"{safe_title}_P{choice+1}"

        video_file = f"{base_name}_video.mp4"
        audio_file = f"{base_name}_audio.m4a"
        output_file = f"{base_name}.mp4"

        self.log("开始并发下载视频和音频...")
        download_errors = []

        def download_video():
            try:
                download_file(session, video_url, video_file, progress_callback=self.update_progress)
                self.log("视频下载完成")
            except Exception as e:
                self.log(f"视频下载失败: {e}", "ERROR")
                download_errors.append(("视频", e))

        def download_audio():
            try:
                download_file(session, audio_url, audio_file, progress_callback=self.update_progress)
                self.log("音频下载完成")
            except Exception as e:
                self.log(f"音频下载失败: {e}", "ERROR")
                download_errors.append(("音频", e))

        t1 = threading.Thread(target=download_video)
        t2 = threading.Thread(target=download_audio)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        if download_errors:
            self.log("下载过程中出现错误，终止", "ERROR")
            self.status_var.set("错误")
            self.is_downloading = False
            self.root.after(0, lambda: messagebox.showerror("错误", f"下载失败:\n{download_errors[0][1]}"))
            return

        if not self.no_merge_var.get():
            self.log("正在合并视频和音频 (需要 ffmpeg)...")
            success, err = merge_with_ffmpeg(video_file, audio_file, output_file)
            if success:
                self.log(f"合并成功: {output_file}")
                try:
                    os.remove(video_file)
                    os.remove(audio_file)
                except:
                    pass
                final_path = os.path.abspath(output_file)
                self.log(f"最终文件: {final_path}")
                if self.open_folder_var.get():
                    os.startfile(os.path.dirname(final_path))
            else:
                self.log(f"合并失败: {err}", "ERROR")
                self.log(f"保留分离文件: {video_file} 和 {audio_file}")
        else:
            self.log(f"已下载分离文件: {video_file} 和 {audio_file}")
            if self.open_folder_var.get():
                os.startfile(os.path.dirname(os.path.abspath(video_file)))

        self.log("下载完成！")
        self.status_var.set("完成")
        self.progress['value'] = 100
        self.is_downloading = False

    def show_about(self):
        about_text = f"""B站视频下载器 v{__version__}

功能:
• 支持单个或批量下载 (每行一个 BV/URL)
• 自动 WBI 签名，无需手动获取
• 多 P 视频选择
• 音视频分离下载并合并 (需 ffmpeg)
• Cookies 自动获取 (浏览器) 或手动指定文件
• 并发下载，速度更快
• 亮色/暗色主题切换 (Windows 11 风格)
• 下载历史记录，避免重复下载
• 下载完成后自动打开文件夹

更新日志 (v2.3):
- 修复分P卡顿问题
- 右键粘贴功能
- 亮暗主题切换 (sv-ttk)
- 批量下载
- 下载历史
- 并发下载
- 自动打开文件夹

说明文档:
• 使用前请确保已登录 B 站 (用于获取高画质)
• 如需自动合并，请安装 ffmpeg 并添加至 PATH
• 可勾选「不合并」仅下载音视频分离文件
• Cookies 优先级: 指定文件 > 本地 cookies.json > 浏览器自动获取

GitHub 项目:
• 本项目: https://github.com/FDLAlfrid/BLD
• 其他项目: https://github.com/FDLAlfrid/B-

感谢使用！
"""
        dialog = tk.Toplevel(self.root)
        dialog.title("关于")
        dialog.geometry("500x400")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        text_widget = tk.Text(dialog, wrap=tk.WORD, font=("微软雅黑", 9))
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, about_text)
        text_widget.config(state=tk.DISABLED)

        def open_github():
            webbrowser.open("https://github.com/FDLAlfrid/BLD")
        btn_github = ttk.Button(dialog, text="打开 GitHub 仓库", command=open_github)
        btn_github.pack(pady=5)

        btn_close = ttk.Button(dialog, text="关闭", command=dialog.destroy)
        btn_close.pack(pady=5)

    def show_history(self):
        if not self.history:
            messagebox.showinfo("历史记录", "暂无下载历史")
            return
        history_text = "\n".join([f"{h.get('time','')} - {h.get('title','')} ({h.get('bvid','')})" for h in self.history[-20:]])
        messagebox.showinfo("下载历史 (最近20条)", history_text)

# ---------- 主程序入口 ----------
def main():
    root = tk.Tk()
    app = BiliDownloaderApp(root)
    root.mainloop()

if __name__ == "__main__":
    try:
        import browser_cookie3
    except ImportError:
        pass
    main()
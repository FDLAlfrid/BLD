#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站视频下载工具 - GUI版 (sv-ttk 主题)
版本: 2.4.1 (Edge Cookie 读取优化版)
新增: 排行榜功能 / Edge 浏览器 Cookie 免关闭读取
"""
import re
import json
import time
import hashlib
import subprocess
import os
import sys
import platform
import io
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, Menu
import webbrowser
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

__version__ = "2.4.1"

# ---------- 程序目录（历史 / Cookies / 下载输出都放在此目录，避免写入用户目录） ----------
def get_app_dir():
    """返回程序所在目录：脚本同目录或打包后 exe 同目录"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后的可执行文件所在目录
        return os.path.dirname(sys.executable)
    else:
        # 脚本文件所在目录
        return os.path.dirname(os.path.abspath(__file__))

# ---------- 资源路径（解决打包后图标加载问题） ----------
def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = get_app_dir()
    return os.path.join(base_path, relative_path)

# ---------- 配置 ----------
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
}
HISTORY_FILE = os.path.join(get_app_dir(), "history.json")
THEME_FILE = os.path.join(get_app_dir(), "theme.json")
COVER_CACHE_DIR = os.path.join(get_app_dir(), "cache", "covers")

# ---------- 主题持久化 ----------
def load_theme() -> str:
    try:
        with open(THEME_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            t = str(data.get("theme", "light")).lower()
            return t if t in ("light", "dark") else "light"
    except Exception:
        return "light"

def save_theme(theme: str):
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            json.dump({"theme": theme}, f)
    except Exception:
        pass

# ---------- 全局字体常量 ----------
FONT_FAMILY = "微软雅黑"
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
FONT_TITLE = (FONT_FAMILY, 11, "bold")
FONT_LARGE = (FONT_FAMILY, 12, "bold")
FONT_MENU = (FONT_FAMILY, 11)
FONT_DIALOG = (FONT_FAMILY, 11)
FONT_DIALOG_LARGE = (FONT_FAMILY, 12, "bold")

# ---------- 工具函数 ----------
def format_count(n, mode="auto"):
    try:
        n = int(n)
    except Exception:
        n = 0
    if mode == "auto":
        if n >= 100000000:
            return f"{n/100000000:.1f}亿"
        if n >= 10000:
            return f"{n/10000:.1f}W"
        if n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)
    if mode == "wan":
        if n >= 10000:
            return f"{n/10000:.1f}W"
        return str(n)
    if mode == "k":
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        if n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)
    return f"{n:,}"

def get_session_with_retry():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

def parse_input(text):
    text = text.strip()
    url_match = re.search(r'https?://[^\s]+', text)
    if url_match:
        text = url_match.group(0)
    if text.startswith("b23.tv/"):
        text = "https://" + text
    if text.startswith("http"):
        if "b23.tv/" in text:
            try:
                resp = requests.head(text, headers=HEADERS, allow_redirects=True, timeout=10)
                real_url = resp.url
            except Exception:
                try:
                    resp = requests.get(text, headers=HEADERS, allow_redirects=True, timeout=10, stream=True)
                    real_url = resp.url
                    resp.close()
                except Exception as e:
                    raise ValueError(f"短链接解析失败: {e}")
            text = real_url
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

# ====================== Cookie 自动获取核心优化 ======================
def _try_get_edge_cookies(browser_func):
    """Edge Cookie 三层兜底读取：直读 → 指定路径 → 临时副本绕过文件锁"""
    default_cookie_path = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies"
    )
    
    if not os.path.exists(default_cookie_path):
        return None
    
    # 第1层：默认方式直接读取
    try:
        cj = browser_func(domain_name=".bilibili.com")
        cookies = {c.name: c.value for c in cj if ".bilibili.com" in c.domain or "bilibili.com" in c.domain}
        if cookies and "SESSDATA" in cookies:
            return cookies
    except Exception:
        pass
    
    # 第2层：显式指定 Cookie 文件路径读取
    try:
        cj = browser_func(cookie_file=default_cookie_path, domain_name=".bilibili.com")
        cookies = {c.name: c.value for c in cj if ".bilibili.com" in c.domain or "bilibili.com" in c.domain}
        if cookies and "SESSDATA" in cookies:
            return cookies
    except Exception:
        pass
    
    # 第3层：复制到临时目录读取（核心：绕过浏览器文件锁）
    try:
        temp_dir = tempfile.gettempdir()
        temp_cookie = os.path.join(temp_dir, f"bld_edge_cookie_{int(time.time())}.db")
        shutil.copy2(default_cookie_path, temp_cookie)
        
        try:
            cj = browser_func(cookie_file=temp_cookie, domain_name=".bilibili.com")
            cookies = {c.name: c.value for c in cj if ".bilibili.com" in c.domain or "bilibili.com" in c.domain}
            if cookies and "SESSDATA" in cookies:
                return cookies
        finally:
            # 清理临时文件
            try:
                os.remove(temp_cookie)
            except Exception:
                pass
    except Exception:
        pass
    
    return None

def get_cookies_from_browser_auto():
    """优先从 Edge 获取 Cookies，支持浏览器运行时读取；失败依次尝试其他浏览器"""
    browsers = ["edge", "chrome", "chromium", "brave", "opera", "firefox"]
    is_windows = platform.system() == "Windows"

    for browser in browsers:
        try:
            import browser_cookie3
            func_name_map = {
                "edge": "edge",
                "chrome": "chrome",
                "chromium": "chromium",
                "brave": "brave",
                "opera": "opera",
                "firefox": "firefox",
            }
            func_name = func_name_map.get(browser, browser)
            
            if not hasattr(browser_cookie3, func_name):
                continue

            browser_func = getattr(browser_cookie3, func_name)
            
            # Windows 下 Edge 走三层兜底逻辑
            if browser == "edge" and is_windows:
                cookies = _try_get_edge_cookies(browser_func)
                if cookies and "SESSDATA" in cookies:
                    return cookies, browser
            else:
                # 其他浏览器正常尝试
                try:
                    cj = browser_func(domain_name=".bilibili.com")
                    cookies = {}
                    for c in cj:
                        if ".bilibili.com" in c.domain or "bilibili.com" in c.domain:
                            cookies[c.name] = c.value
                    if cookies and "SESSDATA" in cookies:
                        return cookies, browser
                except Exception:
                    continue
        except Exception:
            continue
    
    return None, None
# ====================================================================

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
        "-y", output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except FileNotFoundError:
        return False, "未找到 ffmpeg，请安装并添加到 PATH"

def fetch_danmaku_xml(session, cid, cookies=None):
    all_danmaku = []
    segment_index = 1
    max_segments = 50
    while segment_index <= max_segments:
        url = "https://api.bilibili.com/x/v2/dm/list/seg.so"
        params = {
            "type": 1,
            "oid": cid,
            "mode": 1,
            "segment_index": segment_index,
        }
        try:
            resp = session.get(url, params=params, headers=HEADERS, cookies=cookies, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break
        if data.get("code") != 0:
            break
        seg_data = data.get("data", {})
        seg_list = seg_data.get("seg", [])
        if not seg_list:
            break
        for seg in seg_list:
            dm_list = seg.get("dm", [])
            all_danmaku.extend(dm_list)
            if seg.get("flag") is True:
                segment_index += 1
            else:
                break
        else:
            break
    if not all_danmaku:
        return _fetch_danmaku_xml_fallback(session, cid, cookies)
    lines = ['<i>']
    for dm in all_danmaku:
        progress = dm.get("progress", 0)
        mode = dm.get("mode", 1)
        fontsize = dm.get("fontsize", 25)
        color = dm.get("color", 16777215)
        ctime = dm.get("ctime", 0)
        pool = dm.get("pool", 0)
        uid_hash = dm.get("uid_hash", "0")
        dm_id = dm.get("id", 0)
        content = dm.get("content", "")
        content_escaped = (content
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))
        p_attr = f'{progress},{mode},{fontsize},{color},{ctime},{pool},{uid_hash},{dm_id}'
        lines.append(f'  <d p="{p_attr}">{content_escaped}</d>')
    lines.append('</i>')
    return '\n'.join(lines)

def _fetch_danmaku_xml_fallback(session, cid, cookies=None):
    url = f"https://api.bilibili.com/x/v1/dm/list.so"
    params = {"oid": cid}
    resp = session.get(url, params=params, headers=HEADERS, cookies=cookies, timeout=15)
    resp.raise_for_status()
    return resp.text

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

# ---------- 排行榜相关函数 ----------
FALLBACK_ZONES = {
    "全站": 0,
    "动画": 1,
    "番剧": 13,
    "国创": 168,
    "游戏": 4,
    "音乐": 3,
    "舞蹈": 129,
    "科技": 188,
    "知识": 36,
    "生活": 160,
    "美食": 211,
    "汽车": 217,
    "时尚": 155,
    "运动": 234,
    "影视": 181,
    "纪录片": 177,
    "电影": 23,
    "电视剧": 11,
}

def fetch_zones_from_github():
    url = "https://raw.githubusercontent.com/SocialSisterYi/bilibili-API-collect/master/docs/video/zone.md"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        zones = {}
        for line in lines:
            line = line.strip()
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                tid_str = parts[0]
                name = parts[1]
                zone_type = parts[2]
                if zone_type in ("主分区", ""):
                    tid_str = tid_str.strip("`")
                    if tid_str.isdigit():
                        tid = int(tid_str)
                        zones[name] = tid
        return zones
    except Exception:
        return None

def get_ranking_data(rid, rank_type="hot"):
    try:
        if rank_type == "popular":
            url = "https://api.bilibili.com/x/web-interface/popular/precious"
            params = {"page": 1, "pagesize": 100}
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                return None
            return data["data"]["list"]
        if rank_type == "latest":
            url = "https://api.bilibili.com/x/web-interface/newlist"
            params = {"rid": rid, "ps": 30, "pn": 1}
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                return None
            return data["data"]["archives"]
        url = "https://api.bilibili.com/x/web-interface/ranking/v2"
        params = {"rid": rid, "type": "all"}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return None
        return data["data"]["list"]
    except Exception:
        return None

# ---------- GUI 应用程序 ----------
class BiliDownloaderApp:
    def __init__(self, root):
        self.root = root
        root.title(f"B站视频下载器 v{__version__}")
        root.geometry("800x600")
        root.minsize(700, 480)

        # ----- 设置窗口图标（标题栏和任务栏） -----
        icon_path = resource_path("B站下载器icon.ico")
        if os.path.exists(icon_path):
            try:
                root.iconbitmap(default=icon_path)
            except Exception:
                pass

        # 主题变量（从持久化文件加载，默认 light）
        self._theme = load_theme()
        self.current_theme = tk.StringVar(value=self._theme)

        # 变量 (下载页)
        self.input_var = tk.StringVar()
        self.qn_var = tk.IntVar(value=80)
        self.output_var = tk.StringVar()
        self.cookies_file_var = tk.StringVar()
        self.use_cookies_var = tk.BooleanVar(value=True)
        self.no_merge_var = tk.BooleanVar(value=False)
        self.skip_history_var = tk.BooleanVar(value=True)
        self.open_folder_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.batch_mode_var = tk.BooleanVar(value=False)
        self.exit_after_var = tk.BooleanVar(value=False)
        self.auto_paste_var = tk.BooleanVar(value=False)
        self.custom_dir_var = tk.BooleanVar(value=False)
        self.custom_dir_var_path = tk.StringVar()
        self.with_danmaku_var = tk.BooleanVar(value=False)

        # 下载状态
        self.download_params = None
        self.is_downloading = False
        self.history = load_history()

        # 设置全局 ttk 样式（统一字体、行高）
        self.setup_style()

        # 创建菜单栏
        self.create_menu()

        # 创建 Notebook (标签页)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ---- 下载标签页 ----
        self.download_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.download_frame, text="下载")
        self.create_download_tab()

        # ---- 排行榜标签页 ----
        self.ranking_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.ranking_frame, text="排行榜")
        self.create_ranking_tab()

        # 绑定右键菜单（下载页输入框）
        self.setup_context_menu()

        # 应用主题（使用已加载的持久化主题）
        self.apply_theme(self._theme)

        # 延迟到首次切换到排行榜标签页时再初始化（避免启动卡顿）
        self._ranking_initialized = False
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ====================================================================
    # 全局样式 / 字体
    # ====================================================================
    def _on_tab_changed(self, event=None):
        if not self._ranking_initialized:
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 1:  # 排行榜标签页
                self._ranking_initialized = True
                self.init_ranking_zones()

    def setup_style(self):
        s = ttk.Style()
        s.configure(".", font=FONT_BODY)
        s.configure("TLabel", font=FONT_BODY)
        s.configure("TButton", font=FONT_BODY)
        s.configure("TCheckbutton", font=FONT_BODY)
        s.configure("TRadiobutton", font=FONT_BODY)
        s.configure("TEntry", font=FONT_BODY)
        s.configure("TCombobox", font=FONT_BODY)
        s.configure("TNotebook", font=FONT_BODY)
        s.configure("TNotebook.Tab", font=FONT_BODY_BOLD, padding=(12, 4))
        s.configure("TLabelframe.Label", font=FONT_TITLE)
        s.configure("Horizontal.TProgressbar", thickness=12)
        s.configure("Treeview", font=FONT_BODY, rowheight=26)
        s.configure("Treeview.Heading", font=FONT_BODY_BOLD)
        self.root.option_add("*Menu.font", FONT_MENU)
        self.root.option_add("*Menu.tearOff", 0)

    # ---------- 菜单 ----------
    def create_menu(self):
        menubar = Menu(self.root)
        self.menubar = menubar
        self._menus = [menubar]
        self.root.config(menu=menubar)

        theme_menu = Menu(menubar, tearoff=0)
        self._menus.append(theme_menu)
        menubar.add_cascade(label="主题", menu=theme_menu)
        theme_menu.add_command(label="亮色", command=lambda: self.apply_theme("light"))
        theme_menu.add_command(label="暗色", command=lambda: self.apply_theme("dark"))

        help_menu = Menu(menubar, tearoff=0)
        self._menus.append(help_menu)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="关于", command=self.show_about)
        help_menu.add_command(label="查看历史", command=self.show_history)

    # ====================================================================
    # 主题系统（统一调色板 + 通用辅助方法 + 全局应用）
    # ====================================================================
    def apply_theme(self, theme):
        if theme not in ("light", "dark"):
            theme = "light"
        self._theme = theme
        self.current_theme.set(theme)
        save_theme(theme)
        if HAS_SV_TTK:
            sv_ttk.set_theme(theme)
        else:
            c = self._get_theme_colors()
            self.root.tk_setPalette(
                background=c["dialog_bg"],
                foreground=c["fg"],
                activeBackground=c["menu_active_bg"],
                activeForeground=c["menu_active_fg"],
                highlightBackground=c["border"],
                highlightColor=c["accent"]
            )
        self._apply_theme_to_all()

    def _get_theme_colors(self):
        if getattr(self, "_theme", "light") == "dark":
            return {
                "bg": "#1e1e1e",
                "fg": "#d4d4d4",
                "insert": "#ffffff",
                "select_bg": "#094771",
                "select_fg": "#ffffff",
                "tree_bg": "#252526",
                "tree_fg": "#d4d4d4",
                "tree_sel_bg": "#094771",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#3c3c3c",
                "tree_heading_fg": "#d4d4d4",
                "tree_border": "#555555",
                "dialog_bg": "#1e1e1e",
                "canvas_bg": "#1e1e1e",
                "root_bg": "#1e1e1e",
                "menu_bg": "#2d2d2d",
                "menu_fg": "#d4d4d4",
                "menu_active_bg": "#094771",
                "menu_active_fg": "#ffffff",
                "menu_border": "#3c3c3c",
                "accent": "#0078d7",
                "border": "#3c3c3c",
                "log_info": "#d4d4d4",
                "log_warning": "#ffcc00",
                "log_error": "#f44747",
            }
        else:
            return {
                "bg": "#ffffff",
                "fg": "#000000",
                "insert": "#000000",
                "select_bg": "#0078d7",
                "select_fg": "#ffffff",
                "tree_bg": "#ffffff",
                "tree_fg": "#000000",
                "tree_sel_bg": "#0078d7",
                "tree_sel_fg": "#ffffff",
                "tree_heading_bg": "#f0f0f0",
                "tree_heading_fg": "#000000",
                "tree_border": "#cccccc",
                "dialog_bg": "#f0f0f0",
                "canvas_bg": "#ffffff",
                "root_bg": "#f0f0f0",
                "menu_bg": "#f0f0f0",
                "menu_fg": "#000000",
                "menu_active_bg": "#0078d7",
                "menu_active_fg": "#ffffff",
                "menu_border": "#cccccc",
                "accent": "#0078d7",
                "border": "#cccccc",
                "log_info": "#000000",
                "log_warning": "#cc7700",
                "log_error": "#d12c2c",
            }

    # ---------- 通用主题辅助方法 ----------
    def _theme_text_widget(self, widget):
        c = self._get_theme_colors()
        widget.config(
            bg=c["bg"], fg=c["fg"],
            insertbackground=c["insert"],
            selectbackground=c["select_bg"],
            selectforeground=c["select_fg"],
            borderwidth=0, highlightthickness=0
        )

    def _theme_menu(self, menu):
        c = self._get_theme_colors()
        try:
            menu.config(
                bg=c["menu_bg"], fg=c["menu_fg"],
                activebackground=c["menu_active_bg"],
                activeforeground=c["menu_active_fg"],
                borderwidth=0, relief=tk.FLAT
            )
        except tk.TclError:
            pass

    def _theme_treeview(self, tree, style_name):
        c = self._get_theme_colors()
        style = ttk.Style()
        style.configure(
            style_name,
            background=c["tree_bg"],
            foreground=c["tree_fg"],
            fieldbackground=c["tree_bg"],
            rowheight=24,
            borderwidth=0,
            relief=tk.FLAT
        )
        style.map(
            style_name,
            background=[("selected", c["tree_sel_bg"])],
            foreground=[("selected", c["tree_sel_fg"])]
        )
        style.configure(
            f"{style_name}.Heading",
            background=c["tree_heading_bg"],
            foreground=c["tree_heading_fg"],
            borderwidth=0,
            relief=tk.FLAT,
            font=FONT_BODY_BOLD
        )
        style.map(
            f"{style_name}.Heading",
            background=[("active", c["menu_active_bg"])],
            foreground=[("active", c["menu_active_fg"])]
        )
        try:
            tree.configure(style=style_name)
        except tk.TclError:
            pass

    def _theme_toplevel(self, dialog):
        c = self._get_theme_colors()
        dialog.config(bg=c["dialog_bg"])
        dialog.option_add("*Toplevel.background", c["dialog_bg"])
        dialog.option_add("*Frame.background", c["dialog_bg"])
        dialog.option_add("*Label.background", c["dialog_bg"])
        dialog.option_add("*Label.foreground", c["fg"])
        return dialog

    def _apply_theme_to_all(self):
        """应用当前主题到所有已存在的 tk 原生控件"""
        c = self._get_theme_colors()
        self.root.config(bg=c["root_bg"])
        if hasattr(self, "entry"):
            self._theme_text_widget(self.entry)
        if hasattr(self, "log_text"):
            self._theme_text_widget(self.log_text)
            self._configure_log_tags()
        if hasattr(self, "ranking_tree"):
            self._theme_treeview(self.ranking_tree, "Ranking.Treeview")
        if hasattr(self, "card_canvas"):
            self.card_canvas.config(bg=c["canvas_bg"], highlightthickness=0)
        if hasattr(self, "_menus"):
            for m in self._menus:
                self._theme_menu(m)
        if hasattr(self, "context_menu"):
            self._theme_menu(self.context_menu)

    def _configure_log_tags(self):
        c = self._get_theme_colors()
        try:
            self.log_text.tag_config("INFO", foreground=c["log_info"])
            self.log_text.tag_config("WARNING", foreground=c["log_warning"])
            self.log_text.tag_config("ERROR", foreground=c["log_error"])
        except tk.TclError:
            pass

    def _theme_listbox(self, listbox):
        c = self._get_theme_colors()
        listbox.config(
            bg=c["tree_bg"], fg=c["tree_fg"],
            selectbackground=c["tree_sel_bg"],
            selectforeground=c["tree_sel_fg"],
            borderwidth=0, highlightthickness=0, relief=tk.FLAT
        )

    # ---------- 主题化对话框 ----------
    def _show_message(self, title, message, kind="info", parent=None):
        if parent is None:
            parent = self.root
        dialog = self._theme_toplevel(tk.Toplevel(parent))
        dialog.title(title)
        dialog.transient(parent)
        dialog.grab_set()

        max_char = max(len(line) for line in str(message).splitlines()) if message else 20
        wrap = min(max(320, max_char * 12), 560)
        lines = str(message).count("\n") + 1
        height = max(120, 70 + lines * 22)
        dialog.geometry(f"{wrap + 40}x{height}")
        dialog.resizable(False, False)

        icon_map = {"info": "ℹ", "warning": "⚠", "error": "✕", "confirm": "?"}
        c = self._get_theme_colors()
        icon_text = icon_map.get(kind, "ℹ")

        msg_frame = ttk.Frame(dialog)
        msg_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(15, 8))
        ttk.Label(msg_frame, text=icon_text, font=(FONT_FAMILY, 22, "bold"), foreground=c["accent"]).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(msg_frame, text=message, font=FONT_DIALOG, wraplength=wrap).pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(4, 14))
        result = {"value": False}

        def _close(val):
            result["value"] = val
            dialog.destroy()

        if kind == "confirm":
            ttk.Button(btn_frame, text="确定", command=lambda: _close(True)).pack(side=tk.LEFT, padx=8)
            ttk.Button(btn_frame, text="取消", command=lambda: _close(False)).pack(side=tk.LEFT, padx=8)
            dialog.bind("<Return>", lambda e: _close(True))
            dialog.bind("<Escape>", lambda e: _close(False))
        else:
            ttk.Button(btn_frame, text="确定", command=lambda: _close(True)).pack(side=tk.LEFT, padx=8)
            dialog.bind("<Return>", lambda e: _close(True))
            dialog.bind("<Escape>", lambda e: _close(True))

        dialog.wait_window()
        return result["value"]

    def _show_info(self, title, message, parent=None):
        return self._show_message(title, message, "info", parent)

    def _show_warning(self, title, message, parent=None):
        return self._show_message(title, message, "warning", parent)

    def _show_error(self, title, message, parent=None):
        return self._show_message(title, message, "error", parent)

    def _show_confirm(self, title, message, parent=None):
        return self._show_message(title, message, "confirm", parent)

    def _select_page_dialog(self, pages, p_list):
        dialog = self._theme_toplevel(tk.Toplevel(self.root))
        dialog.title("选择分 P")
        dialog.transient(self.root)
        dialog.grab_set()
        n = len(pages)
        dialog.geometry(f"480x{min(120 + n * 22, 520)}")
        dialog.resizable(False, True)

        ttk.Label(dialog, text=f"请选择要下载的分 P (1-{n})：", font=FONT_DIALOG).pack(anchor=tk.W, padx=15, pady=(12, 4))

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=4)
        listbox = tk.Listbox(list_frame, font=FONT_BODY, selectmode=tk.BROWSE, activestyle=tk.NONE, borderwidth=0, highlightthickness=0)
        self._theme_listbox(listbox)
        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=vsb.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        for item in p_list:
            listbox.insert(tk.END, item)
        listbox.selection_set(0)
        listbox.see(0)

        result = {"value": None}

        def _confirm():
            sel = listbox.curselection()
            if sel:
                result["value"] = sel[0]
                dialog.destroy()

        def _cancel():
            result["value"] = None
            dialog.destroy()

        listbox.bind("<Double-1>", lambda e: _confirm())

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(4, 12))
        ttk.Button(btn_frame, text="确定", command=_confirm).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="取消", command=_cancel).pack(side=tk.LEFT, padx=8)
        dialog.bind("<Return>", lambda e: _confirm())
        dialog.bind("<Escape>", lambda e: _cancel())

        dialog.wait_window()
        return result["value"]

    # ---------- 下载标签页 ----------
    def create_download_tab(self):
        main_frame = ttk.Frame(self.download_frame, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(2, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # ---- 输入区域 (row=0) ----
        input_frame = ttk.LabelFrame(main_frame, text="视频输入", padding="5")
        input_frame.grid(row=0, column=0, sticky=tk.EW, pady=5)
        input_frame.columnconfigure(0, weight=1)
        input_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(input_frame, text="批量模式 (每行一个)", variable=self.batch_mode_var).grid(row=0, column=0, sticky=tk.W, padx=5)

        self.entry = tk.Text(input_frame, height=3 if self.batch_mode_var.get() else 1, font=FONT_BODY)
        self.entry.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=5)
        self.batch_mode_var.trace('w', self.toggle_batch_mode)

        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=1, column=2, padx=5, sticky=tk.N)
        ttk.Button(btn_frame, text="解析并下载", command=self.start_download).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="查看历史", command=self.show_history).pack(side=tk.LEFT, padx=2)

        # ---- 选项区域 (row=1) ----
        opt_frame = ttk.LabelFrame(main_frame, text="下载选项", padding="5")
        opt_frame.grid(row=1, column=0, sticky=tk.EW, pady=5)
        opt_frame.columnconfigure(2, weight=1)

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
        self.entry_cookie = ttk.Entry(opt_frame, textvariable=self.cookies_file_var, width=30)
        self.entry_cookie.grid(row=2, column=1, sticky=tk.W, padx=5)
        cookie_btn_frame = ttk.Frame(opt_frame)
        cookie_btn_frame.grid(row=2, column=2, sticky=tk.W, padx=5)
        self.browse_cookie_btn = ttk.Button(cookie_btn_frame, text="浏览", command=self.browse_cookie)
        self.browse_cookie_btn.pack(side=tk.LEFT)
        self.use_cookies_cb = ttk.Checkbutton(cookie_btn_frame, text="使用Cookies", variable=self.use_cookies_var, command=self._toggle_cookie_controls)
        self.use_cookies_cb.pack(side=tk.LEFT, padx=(5, 0))
        self._toggle_cookie_controls()

        ttk.Checkbutton(opt_frame, text="不合并(分别下载音视频)", variable=self.no_merge_var).grid(row=3, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="跳过已下载 (历史)", variable=self.skip_history_var).grid(row=3, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="完成后打开文件夹", variable=self.open_folder_var).grid(row=3, column=2, sticky=tk.W, padx=5)

        ttk.Checkbutton(opt_frame, text="下载完成后关闭程序", variable=self.exit_after_var).grid(row=4, column=0, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="窗口获焦自动粘贴剪贴板", variable=self.auto_paste_var).grid(row=4, column=1, sticky=tk.W, padx=5)
        ttk.Checkbutton(opt_frame, text="下载到指定目录", variable=self.custom_dir_var, command=self._toggle_custom_dir).grid(row=4, column=2, sticky=tk.W, padx=5)

        ttk.Checkbutton(opt_frame, text="下载弹幕 (XML)", variable=self.with_danmaku_var).grid(row=5, column=0, sticky=tk.W, padx=5)

        self.custom_dir_frame = ttk.Frame(opt_frame)
        self.custom_dir_frame.grid(row=6, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=2)
        self.custom_dir_frame.columnconfigure(1, weight=1)
        ttk.Label(self.custom_dir_frame, text="目录:").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Entry(self.custom_dir_frame, textvariable=self.custom_dir_var_path).grid(row=0, column=1, sticky=tk.EW, padx=5)
        ttk.Button(self.custom_dir_frame, text="浏览", command=self.browse_custom_dir).grid(row=0, column=2, padx=5)
        self.custom_dir_frame.grid_remove()

        self.root.bind("<FocusIn>", self._on_window_focus_in)

        # ---- 日志区域 (row=2) ----
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="5")
        log_frame.grid(row=2, column=0, sticky=tk.NSEW, pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=0)

        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD, state=tk.DISABLED, font=FONT_BODY)
        self._bind_copy_menu(self.log_text)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar.grid(row=0, column=1, sticky=tk.NS)

        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))
        ttk.Button(log_btn_frame, text="清空日志", command=self.clear_log).pack(side=tk.RIGHT, padx=2)
        ttk.Button(log_btn_frame, text="导出日志", command=self.export_log).pack(side=tk.RIGHT, padx=2)

        # ---- 状态栏 (row=3) ----
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=3, column=0, sticky=tk.EW, pady=2)
        status_frame.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(status_frame, mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, width=22, font=FONT_SMALL)
        self.status_label.pack(side=tk.RIGHT, padx=5)

    def toggle_batch_mode(self, *args):
        if self.batch_mode_var.get():
            self.entry.config(height=4)
        else:
            self.entry.config(height=1)

    # ---------- Text 控件工具：复制菜单 ----------
    def _bind_copy_menu(self, text_widget):
        menu = Menu(self.root, tearoff=0)

        def _copy():
            try:
                text_widget.clipboard_clear()
                sel = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
                text_widget.clipboard_append(sel)
            except tk.TclError:
                pass

        def _select_all():
            text_widget.tag_add(tk.SEL, "1.0", tk.END + "-1c")
            text_widget.mark_set(tk.INSERT, "1.0")
            text_widget.see(tk.INSERT)

        menu.add_command(label="全选 Ctrl+A", command=_select_all)
        menu.add_command(label="复制 Ctrl+C", command=_copy)

        def show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        text_widget.bind("<Button-3>", show_menu)
        text_widget.bind("<Control-c>", lambda e: (_copy(), "break"))
        text_widget.bind("<Control-C>", lambda e: (_copy(), "break"))
        text_widget.bind("<Control-a>", lambda e: (_select_all(), "break"))
        text_widget.bind("<Control-A>", lambda e: (_select_all(), "break"))

    def setup_context_menu(self):
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="粘贴", command=self.paste_from_clipboard)
        self.entry.bind("<Button-3>", self.show_context_menu)
        self.entry.bind("<<Paste>>", self.paste_from_clipboard)
        self.entry.bind("<Shift-Insert>", self.paste_from_clipboard)

    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def paste_from_clipboard(self, event=None):
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            clipboard_text = ""
        if not clipboard_text:
            return

        if self.batch_mode_var.get():
            parts = re.split(r"[\n,;，；]+", clipboard_text)
            new_lines = []
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if re.search(r'https?://', p):
                    new_lines.append(p)
                else:
                    for sub in re.split(r"\s+", p):
                        sub = sub.strip()
                        if sub:
                            new_lines.append(sub)

            existing_raw = self.entry.get("1.0", tk.END).strip()
            existing_lines = []
            existing_seen = set()
            if existing_raw:
                for line in existing_raw.splitlines():
                    line = line.strip()
                    if line and line not in existing_seen:
                        existing_seen.add(line)
                        existing_lines.append(line)

            merged = list(existing_lines)
            for line in new_lines:
                if line not in existing_seen:
                    existing_seen.add(line)
                    merged.append(line)

            text_to_insert = "\n".join(merged)
            self.entry.delete(1.0, tk.END)
            if text_to_insert:
                self.entry.insert(1.0, text_to_insert)
        else:
            text_to_insert = clipboard_text.strip().splitlines()[0] if clipboard_text.strip() else ""
            self.entry.delete(1.0, tk.END)
            if text_to_insert:
                self.entry.insert(1.0, text_to_insert)

        if event is not None:
            return "break"

    def browse_cookie(self):
        filename = filedialog.askopenfilename(
            title="选择 Cookies 文件",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            self.cookies_file_var.set(filename)

    def _toggle_cookie_controls(self):
        state = tk.NORMAL if self.use_cookies_var.get() else tk.DISABLED
        self.browse_cookie_btn.config(state=state)
        self.entry_cookie.config(state=state)

    def _toggle_custom_dir(self):
        if self.custom_dir_var.get():
            self.custom_dir_frame.grid()
        else:
            self.custom_dir_frame.grid_remove()

    def browse_custom_dir(self):
        dirname = filedialog.askdirectory(title="选择下载目录")
        if dirname:
            self.custom_dir_var_path.set(dirname)

    def _on_window_focus_in(self, event=None):
        if self.auto_paste_var.get() and not self.is_downloading:
            try:
                clipboard_text = self.root.clipboard_get()
                if clipboard_text and not self.entry.get("1.0", tk.END).strip():
                    self.paste_from_clipboard()
            except tk.TclError:
                pass

    def log(self, msg, level="INFO"):
        level = level.upper()
        if level not in ("INFO", "WARNING", "ERROR"):
            level = "INFO"
        self.log_text.config(state=tk.NORMAL)
        start = self.log_text.index(tk.END)
        self.log_text.insert(tk.END, f"[{level}] {msg}\n")
        end = self.log_text.index(tk.END)
        self.log_text.tag_add(level, start, end)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def export_log(self):
        log_content = self.log_text.get("1.0", tk.END).strip()
        if not log_content:
            self._show_info("提示", "日志为空，无需导出")
            return
        filename = filedialog.asksaveasfilename(
            title="导出日志",
            defaultextension=".txt",
            initialfile=f"bili_log_{time.strftime('%Y%m%d_%H%M%S')}.txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(log_content)
                self.log(f"日志已导出: {filename}")
            except Exception as e:
                self._show_error("错误", f"导出失败: {e}")

    def update_progress(self, percent, downloaded, total):
        now = time.monotonic()
        if not hasattr(self, '_last_progress_update'):
            self._last_progress_update = 0
        if percent < 100.0 and (now - self._last_progress_update) < 0.2:
            return
        self._last_progress_update = now

        self.progress['value'] = percent
        pct_str = f"{percent:5.1f}%"
        if total > 0:
            bar_len = 20
            filled = int(bar_len * percent / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            self.status_var.set(f"{pct_str} {bar}")
        else:
            self.status_var.set(f"{pct_str}")
        self.root.update_idletasks()

    # ---------- 下载核心逻辑 ----------
    def start_download(self):
        if self.is_downloading:
            self._show_info("提示", "正在下载中，请稍候")
            return

        input_text = self.entry.get(1.0, tk.END).strip()
        if not input_text:
            self._show_error("错误", "请输入视频 URL、BV 或 AV 号")
            return

        if self.batch_mode_var.get():
            items = [line.strip() for line in input_text.splitlines() if line.strip()]
        else:
            items = [input_text]

        if not items:
            self._show_error("错误", "未检测到有效输入")
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
            self.log("未能获取有效登录 Cookies，将使用无 Cookie 模式（清晰度受限）", "WARNING")

        session = get_session_with_retry()
        try:
            video_info = get_video_info(
                session,
                bvid=id_val if id_type=="bvid" else None,
                aid=id_val if id_type=="aid" else None,
                cookies=cookies
            )
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
            choice = self._select_page_dialog(pages, p_list)
            if choice is None:
                self.log("用户取消选择", "WARNING")
                return

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

        success = self.download_single_worker()
        if success:
            history_entry = {
                "bvid": bvid,
                "aid": video_info.get("aid"),
                "title": title,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "path": getattr(self, '_downloaded_file_path', '')
            }
            self.history = [h for h in self.history if h.get("bvid") != bvid]
            self.history.append(history_entry)
            save_history(self.history)
            self.log("已记录下载历史")

    def get_cookies(self):
        if not self.use_cookies_var.get():
            self.log("已禁用 Cookies，使用无 Cookie 模式（清晰度可能受限）", "INFO")
            return None

        cookies = None
        # 优先级1：用户手动指定的 Cookie 文件
        if self.cookies_file_var.get():
            try:
                cookies = load_cookies_from_file(self.cookies_file_var.get())
                self.log(f"已加载 Cookies: 文件 {self.cookies_file_var.get()}")
                return cookies
            except Exception as e:
                self.log(f"加载 cookies 文件失败: {e}", "ERROR")
                self._show_error("错误", f"加载 cookies 失败:\n{e}")
                return None
        else:
            # 优先级2：程序同目录的 cookies.json
            default_file = os.path.join(get_app_dir(), "cookies.json")
            if os.path.exists(default_file):
                try:
                    cookies = load_cookies_from_file(default_file)
                    self.log(f"已加载 Cookies: 本地文件 {default_file}")
                    return cookies
                except Exception as e:
                    self.log(f"加载本地 cookies.json 失败: {e}", "WARNING")

        # 优先级3：从浏览器自动获取（Edge 优先，支持运行中读取）
        self.log("尝试从浏览器自动获取 Cookies（优先 Edge）...")
        try:
            cookies, browser = get_cookies_from_browser_auto()
            if cookies:
                if "SESSDATA" in cookies:
                    self.log(f"已从 {browser} 获取 Cookies（登录有效）")
                    return cookies
                else:
                    self.log(f"从 {browser} 获取到 Cookie，但缺少 SESSDATA，可能未登录B站", "WARNING")
            else:
                self.log("未能从任何浏览器获取有效登录凭证", "WARNING")
                self.log("提示：若浏览器正在运行，可能因文件锁定导致读取失败", "WARNING")
                self.log("可尝试完全关闭浏览器后重试，或手动导出 cookies.json 放到程序目录", "WARNING")
        except Exception as e:
            self.log(f"浏览器自动获取失败: {e}", "WARNING")

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
            video_url, audio_url = get_playurl(
                session, bvid, cid,
                qn=self.qn_var.get(),
                cookies=cookies
            )
            self.log("获取播放地址成功")
        except Exception as e:
            self.log(f"获取播放地址失败: {e}", "ERROR")
            self.root.after(0, lambda: self._show_error("错误", f"获取播放地址失败:\n{e}"))
            self.status_var.set("错误")
            self.is_downloading = False
            return False

        base_name = self.output_var.get().strip()
        if not base_name:
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
            if not safe_title:
                safe_title = f"video_{bvid}"
            base_name = f"{safe_title}_P{choice+1}"

        if self.custom_dir_var.get() and self.custom_dir_var_path.get().strip():
            app_dir = self.custom_dir_var_path.get().strip()
            try:
                os.makedirs(app_dir, exist_ok=True)
            except Exception:
                app_dir = get_app_dir()
        else:
            app_dir = get_app_dir()

        video_file = os.path.join(app_dir, f"{base_name}_video.mp4")
        audio_file = os.path.join(app_dir, f"{base_name}_audio.m4a")
        output_file = os.path.join(app_dir, f"{base_name}.mp4")

        self.log("开始并发下载视频和音频...")
        download_errors = []
        danmaku_xml = None

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

        def download_danmaku():
            if not self.with_danmaku_var.get():
                return
            try:
                self.log("正在获取弹幕...")
                nonlocal danmaku_xml
                danmaku_xml = fetch_danmaku_xml(session, cid, cookies=cookies)
                self.log("弹幕获取完成")
            except Exception as e:
                self.log(f"弹幕获取失败: {e}", "WARNING")

        t1 = threading.Thread(target=download_video)
        t2 = threading.Thread(target=download_audio)
        t3 = threading.Thread(target=download_danmaku)
        t1.start()
        t2.start()
        t3.start()
        t1.join()
        t2.join()
        t3.join()

        if download_errors:
            self.log("下载过程中出现错误，终止", "ERROR")
            self.status_var.set("错误")
            self.is_downloading = False
            self.root.after(0, lambda: self._show_error("错误", f"下载失败:\n{download_errors[0][1]}"))
            return False

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
                self._downloaded_file_path = final_path
            else:
                self.log(f"合并失败: {err}", "ERROR")
                self.log(f"保留分离文件: {video_file} 和 {audio_file}")
                self._downloaded_file_path = os.path.abspath(video_file)
        else:
            self.log(f"已下载分离文件: {video_file} 和 {audio_file}")
            if self.open_folder_var.get():
                os.startfile(os.path.dirname(os.path.abspath(video_file)))
            self._downloaded_file_path = os.path.abspath(video_file)

        if danmaku_xml is not None:
            danmaku_file = os.path.join(app_dir, f"{base_name}.xml")
            try:
                with open(danmaku_file, "w", encoding="utf-8") as f:
                    f.write(danmaku_xml)
                self.log(f"弹幕已保存: {danmaku_file}")
            except Exception as e:
                self.log(f"弹幕保存失败: {e}", "WARNING")

        self.log("下载完成！")
        self.status_var.set("完成")
        self.progress['value'] = 100
        self.is_downloading = False

        if self.exit_after_var.get():
            self.log("3秒后自动关闭程序...")
            self.root.after(3000, self.root.destroy)

        return True

    # ---------- 排行榜标签页 ----------
    def create_ranking_tab(self):
        frame = ttk.Frame(self.ranking_frame, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        ctrl_frame = ttk.Frame(frame)
        ctrl_frame.pack(fill=tk.X, pady=5)

        ttk.Label(ctrl_frame, text="分区:").pack(side=tk.LEFT, padx=(5, 2))
        self.zone_var = tk.StringVar()
        self.zone_combo = ttk.Combobox(ctrl_frame, textvariable=self.zone_var, state="readonly", width=14)
        self.zone_combo.pack(side=tk.LEFT, padx=2)
        self.zone_combo.bind("<<ComboboxSelected>>", self.on_zone_selected)

        self.refresh_btn = ttk.Button(ctrl_frame, text="刷新", command=self.refresh_ranking)
        self.refresh_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(ctrl_frame, text="维度:").pack(side=tk.LEFT, padx=(8, 2))
        self.rank_type_var = tk.StringVar(value="人气榜")
        rank_type_combo = ttk.Combobox(ctrl_frame, textvariable=self.rank_type_var, state="readonly", values=["人气榜", "最新发布", "入站必看"], width=9)
        rank_type_combo.pack(side=tk.LEFT, padx=2)
        rank_type_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_ranking())

        ttk.Label(ctrl_frame, text="单位:").pack(side=tk.LEFT, padx=(8, 2))
        self.unit_var = tk.StringVar(value="自适应")
        unit_combo = ttk.Combobox(ctrl_frame, textvariable=self.unit_var, state="readonly", values=["自适应", "千分位", "W(万)", "K/M"], width=8)
        unit_combo.pack(side=tk.LEFT, padx=2)
        unit_combo.bind("<<ComboboxSelected>>", lambda e: self.apply_unit_change())

        ttk.Label(ctrl_frame, text="数量:").pack(side=tk.LEFT, padx=(8, 2))
        self.ranking_count_var = tk.IntVar(value=20)
        count_combo = ttk.Combobox(ctrl_frame, textvariable=self.ranking_count_var, state="readonly", values=[10, 20, 50, 100], width=5)
        count_combo.pack(side=tk.LEFT, padx=2)
        count_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_ranking())

        ttk.Label(ctrl_frame, text="视图:").pack(side=tk.LEFT, padx=(8, 2))
        self.view_var = tk.StringVar(value="表格")
        view_combo = ttk.Combobox(ctrl_frame, textvariable=self.view_var, state="readonly", values=["表格", "封面卡片"], width=9)
        view_combo.pack(side=tk.LEFT, padx=2)
        view_combo.bind("<<ComboboxSelected>>", lambda e: self.switch_view())

        self.status_ranking = ttk.Label(ctrl_frame, text="就绪")
        self.status_ranking.pack(side=tk.LEFT, padx=(8, 5))

        self.content_frame = ttk.Frame(frame)
        self.content_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # ---- 表格视图 ----
        tree_frame = ttk.Frame(self.content_frame)
        self.tree_view_frame = tree_frame
        columns = ("#", "标题", "UP主", "播放量", "弹幕")
        self.ranking_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12, selectmode="extended")
        self.ranking_tree.heading("#", text="序号")
        self.ranking_tree.heading("标题", text="标题")
        self.ranking_tree.heading("UP主", text="UP主")
        self.ranking_tree.heading("播放量", text="播放量")
        self.ranking_tree.heading("弹幕", text="弹幕")
        self.ranking_tree.column("#", width=50, anchor="center")
        self.ranking_tree.column("标题", width=300)
        self.ranking_tree.column("UP主", width=120)
        self.ranking_tree.column("播放量", width=100, anchor="e")
        self.ranking_tree.column("弹幕", width=80, anchor="e")

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.ranking_tree.yview)
        self.ranking_tree.configure(yscrollcommand=scrollbar.set)
        self.ranking_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.ranking_tree.bind("<Double-1>", self.on_tree_double_click)

        # ---- 卡片视图 ----
        card_frame = ttk.Frame(self.content_frame)
        self.card_view_frame = card_frame
        self.card_canvas = tk.Canvas(card_frame, borderwidth=0, highlightthickness=0)
        card_scroll = ttk.Scrollbar(card_frame, orient=tk.VERTICAL, command=self.card_canvas.yview)
        self.card_inner = ttk.Frame(self.card_canvas)
        self.card_inner.bind("<Configure>", lambda e: self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all")))
        self.card_window = self.card_canvas.create_window((0, 0), window=self.card_inner, anchor="nw")
        self.card_canvas.configure(yscrollcommand=card_scroll.set)
        self.card_canvas.bind("<Configure>", self.on_card_canvas_configure)
        self.card_canvas.bind("<Enter>", lambda e: self._bind_mousewheel(self.card_canvas))
        self.card_canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())
        self.card_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        card_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.card_photo_refs = []
        self.card_widgets = []
        self.current_view = "表格"
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # ---- 底部按钮 ----
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="全选", command=self._select_all_ranking).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="反选", command=self._invert_selection_ranking).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="取消全选", command=self._deselect_all_ranking).pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(btn_frame, text="勾选前:").pack(side=tk.LEFT, padx=(5, 2))
        self.select_n_var = tk.IntVar(value=5)
        ttk.Spinbox(btn_frame, from_=1, to=100, width=4, textvariable=self.select_n_var).pack(side=tk.LEFT)
        ttk.Label(btn_frame, text="项").pack(side=tk.LEFT, padx=(2, 5))
        ttk.Button(btn_frame, text="勾选", command=self._select_first_n).pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(btn_frame, text="下载选中视频", command=self.download_selected_ranking).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开链接 (浏览器)", command=self.open_selected_link).pack(side=tk.LEFT, padx=5)

        ttk.Label(btn_frame, text="提示: 表格支持 Ctrl/Shift 多选；卡片视图用勾选框").pack(side=tk.LEFT, padx=15)

        self.ranking_list = []

    def init_ranking_zones(self):
        self.status_ranking.config(text="加载分区列表...")
        def fetch():
            zones = fetch_zones_from_github()
            self.root.after(0, lambda: self._apply_zones(zones))
        threading.Thread(target=fetch, daemon=True).start()

    def _apply_zones(self, zones):
        if zones is None:
            zones = FALLBACK_ZONES
            self.log("使用内置备用分区列表", "WARNING")
        else:
            self.log("成功获取分区列表", "INFO")

        sorted_names = sorted(zones.keys())
        self.zone_combo['values'] = sorted_names
        self.zone_map = zones
        if sorted_names:
            self.zone_combo.set(sorted_names[0])
            self.refresh_ranking()
        else:
            self.status_ranking.config(text="无可用分区")

    def on_zone_selected(self, event=None):
        self.refresh_ranking()

    def refresh_ranking(self):
        zone_name = self.zone_var.get()
        if not zone_name:
            return
        rid = self.zone_map.get(zone_name)
        if rid is None:
            self._show_error("错误", "未找到该分区ID")
            return

        rank_type_text = self.rank_type_var.get()
        rank_type = {"人气榜": "hot", "最新发布": "latest", "入站必看": "popular"}.get(rank_type_text, "hot")

        self.status_ranking.config(text=f"加载中... ({rank_type_text})")
        self.refresh_btn.config(state=tk.DISABLED)

        for item in self.ranking_tree.get_children():
            self.ranking_tree.delete(item)
        self.ranking_list.clear()

        def fetch():
            data = get_ranking_data(rid, rank_type)
            self.root.after(0, lambda: self.update_ranking_table(data))
        threading.Thread(target=fetch, daemon=True).start()

    def _current_unit_mode(self):
        m = self.unit_var.get()
        if m == "自适应":
            return "auto"
        if m == "W(万)":
            return "wan"
        if m == "K/M":
            return "k"
        return "comma"

    def update_ranking_table(self, data):
        self.refresh_btn.config(state=tk.NORMAL)
        if data is None:
            self.status_ranking.config(text="加载失败，请重试")
            self._show_error("错误", "获取排行榜数据失败，请检查网络")
            return
        if not data:
            self.status_ranking.config(text="该分区暂无排行数据")
            return

        display_count = self.ranking_count_var.get()
        data = data[:display_count]
        mode = self._current_unit_mode()

        for idx, item in enumerate(data, 1):
            bvid = item.get("bvid", "")
            title = item.get("title", "无标题")
            owner = item.get("owner", {})
            up = owner.get("name", "未知")
            stat = item.get("stat", {})
            view = stat.get("view", 0)
            danmaku = stat.get("danmaku", 0)
            pic = item.get("pic", "")

            view_str = format_count(view, mode)
            danmaku_str = format_count(danmaku, mode)

            self.ranking_tree.insert("", tk.END, values=(idx, title, up, view_str, danmaku_str))
            self.ranking_list.append({
                "bvid": bvid,
                "title": title,
                "owner": up,
                "view": view,
                "danmaku": danmaku,
                "pic": pic,
            })

        self.status_ranking.config(text=f"共 {len(data)} 条")
        if self.current_view == "封面卡片":
            self.render_card_view()

    def on_tree_double_click(self, event):
        self.download_selected_ranking()

    def _get_selected_bvids(self):
        bvids = []
        if self.current_view == "表格":
            for item in self.ranking_tree.selection():
                values = self.ranking_tree.item(item, "values")
                if not values:
                    continue
                try:
                    idx = int(values[0]) - 1
                except ValueError:
                    continue
                if 0 <= idx < len(self.ranking_list):
                    bv = self.ranking_list[idx]["bvid"]
                    if bv:
                        bvids.append(bv)
        else:
            for cw in self.card_widgets:
                if cw["select_var"].get() and cw["bvid"]:
                    bvids.append(cw["bvid"])
        return bvids

    def _select_all_ranking(self):
        if self.current_view == "表格":
            self.ranking_tree.selection_set(self.ranking_tree.get_children())
        else:
            for cw in self.card_widgets:
                cw["select_var"].set(True)

    def _deselect_all_ranking(self):
        if self.current_view == "表格":
            self.ranking_tree.selection_remove(self.ranking_tree.get_children())
        else:
            for cw in self.card_widgets:
                cw["select_var"].set(False)

    def _invert_selection_ranking(self):
        if self.current_view == "表格":
            all_items = list(self.ranking_tree.get_children())
            selected = set(self.ranking_tree.selection())
            for it in all_items:
                if it in selected:
                    self.ranking_tree.selection_remove(it)
                else:
                    self.ranking_tree.selection_add(it)
        else:
            for cw in self.card_widgets:
                cw["select_var"].set(not cw["select_var"].get())

    def _select_first_n(self):
        n = self.select_n_var.get()
        if self.current_view == "表格":
            items = list(self.ranking_tree.get_children())[:n]
            self.ranking_tree.selection_remove(self.ranking_tree.selection())
            for it in items:
                self.ranking_tree.selection_add(it)
        else:
            for i, cw in enumerate(self.card_widgets):
                cw["select_var"].set(i < n)

    def download_selected_ranking(self):
        bvids = self._get_selected_bvids()
        if not bvids:
            self._show_info("提示", "请先选中至少一个视频")
            return

        self.notebook.select(self.download_frame)
        if not self.batch_mode_var.get():
            self.batch_mode_var.set(True)
            self.toggle_batch_mode()

        self.entry.delete(1.0, tk.END)
        self.entry.insert(1.0, "\n".join(bvids))

        if len(bvids) == 1:
            msg = f"是否立即下载 {bvids[0]}？"
        else:
            msg = f"是否立即批量下载 {len(bvids)} 个视频？"

        if self._show_confirm("确认", msg):
            self.start_download()

    def open_selected_link(self):
        bvids = self._get_selected_bvids()
        if not bvids:
            self._show_info("提示", "请先选中至少一个视频")
            return
        for bv in bvids:
            webbrowser.open(f"https://www.bilibili.com/video/{bv}")

    # ---------- 视图切换 / 单位切换 / 卡片视图 ----------
    def switch_view(self):
        new_view = self.view_var.get()
        if new_view == self.current_view:
            return
        self.current_view = new_view
        if new_view == "表格":
            self.card_view_frame.pack_forget()
            self.tree_view_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.tree_view_frame.pack_forget()
            self.card_view_frame.pack(fill=tk.BOTH, expand=True)
            self.render_card_view()

    def apply_unit_change(self):
        mode = self._current_unit_mode()
        for child in self.ranking_tree.get_children():
            values = self.ranking_tree.item(child, "values")
            if not values:
                continue
            try:
                idx = int(values[0]) - 1
            except ValueError:
                continue
            if 0 <= idx < len(self.ranking_list):
                info = self.ranking_list[idx]
                self.ranking_tree.item(child, values=(
                    values[0], values[1], values[2],
                    format_count(info["view"], mode),
                    format_count(info["danmaku"], mode),
                ))
        if self.current_view == "封面卡片":
            self.render_card_view()

    def on_card_canvas_configure(self, event):
        self.card_canvas.itemconfig(self.card_window, width=event.width)

    def _bind_mousewheel(self, widget):
        widget.bind_all("<MouseWheel>", lambda e: self.card_canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _unbind_mousewheel(self):
        self.root.unbind_all("<MouseWheel>")

    def _cover_cache_path(self, bvid, pic):
        if not os.path.exists(COVER_CACHE_DIR):
            try:
                os.makedirs(COVER_CACHE_DIR, exist_ok=True)
            except Exception:
                return None
        return os.path.join(COVER_CACHE_DIR, f"{bvid}.jpg")

    def _load_cover_image(self, bvid, pic, target_size=(160, 100)):
        if not HAS_PIL:
            return None
        cache_path = self._cover_cache_path(bvid, pic)
        img = None
        if cache_path and os.path.exists(cache_path):
            try:
                img = Image.open(cache_path)
            except Exception:
                img = None
        if img is None and pic:
            try:
                pic_url = pic if pic.startswith("http") else "https:" + pic
                resp = requests.get(pic_url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
                if cache_path:
                    try:
                        img.save(cache_path, "JPEG")
                    except Exception:
                        pass
            except Exception:
                return None
        if img is not None:
            try:
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize(target_size, resample)
            except Exception:
                pass
        return img

    def render_card_view(self):
        self._cover_gen = getattr(self, "_cover_gen", 0) + 1
        my_gen = self._cover_gen

        for w in self.card_inner.winfo_children():
            w.destroy()
        self.card_photo_refs = []
        self.card_widgets = []
        self._cover_labels = []

        if not HAS_PIL:
            ttk.Label(self.card_inner, text="未安装 Pillow (PIL)，无法显示卡片视图。\n请运行: pip install Pillow", foreground="red").grid(row=0, column=0, padx=10, pady=10)
            return

        if not self.ranking_list:
            ttk.Label(self.card_inner, text="暂无数据，请先刷新排行榜").grid(row=0, column=0, padx=10, pady=10)
            return

        mode = self._current_unit_mode()
        cols = 4
        cover_labels = []

        for i, info in enumerate(self.ranking_list):
            r, c = divmod(i, cols)
            card = ttk.Frame(self.card_inner, relief="groove", borderwidth=1, padding=4)
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            self.card_inner.columnconfigure(c, weight=1)

            select_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(card, variable=select_var).grid(row=0, column=0, sticky="w")

            cover_lbl = ttk.Label(card, text="加载中…", width=22, font=FONT_SMALL, foreground="gray")
            cover_lbl.grid(row=1, column=0, padx=2, pady=2)
            cover_lbl.bind("<Double-1>", lambda e, bv=info["bvid"]: self._open_one_link(bv))

            title = info["title"]
            if len(title) > 22:
                title = title[:21] + "…"
            ttk.Label(card, text=title, wraplength=150, font=FONT_SMALL_BOLD).grid(row=2, column=0, sticky="w", padx=2)
            ttk.Label(card, text=f"UP: {info['owner']}", foreground="gray", font=FONT_SMALL).grid(row=3, column=0, sticky="w", padx=2)

            stat_text = f"播放 {format_count(info['view'], mode)} 弹幕 {format_count(info['danmaku'], mode)}"
            ttk.Label(card, text=stat_text, font=FONT_SMALL).grid(row=4, column=0, sticky="w", padx=2)

            card.bind("<Double-1>", lambda e, bv=info["bvid"]: self._download_one(bv))

            cw = {
                "frame": card,
                "bvid": info["bvid"],
                "title": info["title"],
                "view": info["view"],
                "danmaku": info["danmaku"],
                "select_var": select_var,
            }
            self.card_widgets.append(cw)
            cover_labels.append((cover_lbl, info["bvid"], info["pic"]))

        self._cover_labels = cover_labels
        threading.Thread(target=self._async_load_covers, args=(my_gen,), daemon=True).start()

    def _async_load_covers(self, gen):
        tasks = list(self._cover_labels)
        results = []
        for cover_lbl, bvid, pic in tasks:
            if gen != self._cover_gen:
                return
            try:
                img = self._load_cover_image(bvid, pic)
            except Exception:
                img = None
            results.append((cover_lbl, img))
        if gen == self._cover_gen:
            self.root.after(0, lambda: self._apply_covers_in_batches(results, 0, gen))

    def _apply_covers_in_batches(self, results, start_idx, gen):
        if gen != self._cover_gen:
            return
        batch = results[start_idx:start_idx + 8]
        for lbl, img in batch:
            self._apply_cover_to_label(lbl, img, gen)
        next_idx = start_idx + 8
        if next_idx < len(results):
            self.root.after(30, lambda: self._apply_covers_in_batches(results, next_idx, gen))

    def _apply_cover_to_label(self, lbl, img, gen=None):
        if gen is not None and gen != self._cover_gen:
            return
        if img is not None:
            try:
                photo = ImageTk.PhotoImage(img)
                self.card_photo_refs.append(photo)
                lbl.configure(image=photo, text="", width=0)
            except Exception:
                lbl.configure(image="", text="[封面无效]", foreground="gray", width=22, font=FONT_SMALL)
        else:
            lbl.configure(image="", text="[封面加载失败]", foreground="gray", width=22, font=FONT_SMALL)

    def _download_one(self, bvid):
        self.notebook.select(self.download_frame)
        self.entry.delete(1.0, tk.END)
        self.entry.insert(1.0, bvid)
        if self._show_confirm("确认", f"是否立即下载 {bvid}？"):
            self.start_download()

    def _open_one_link(self, bvid):
        webbrowser.open(f"https://www.bilibili.com/video/{bvid}")

    # ---------- 关于/历史 ----------
    def show_about(self):
        try:
            about_text = f"""B站视频下载器 v{__version__}

功能:
• 支持单个或批量下载 (每行一个 BV/URL)
• 自动 WBI 签名，无需手动获取
• 多 P 视频选择
• 音视频分离下载并合并 (需 ffmpeg)
• 弹幕下载 (XML 格式，可在播放器中加载)
• Cookies 自动获取 (浏览器) 或手动指定文件
• 并发下载，速度更快
• 亮色/暗色主题切换 (Windows 11 风格)
• 下载历史记录，避免重复下载
• 下载完成后自动打开文件夹
• 排行榜浏览 (动态分区，热门视频)

更新日志 (v2.4.1):
- 优化 Edge 浏览器 Cookie 读取逻辑，支持浏览器运行时读取
- Edge 采用三层兜底：直读 → 指定路径 → 临时副本绕过文件锁
- 调整浏览器优先级，Edge 优先尝试
- 增加 SESSDATA 有效性校验，避免假成功
- 优化失败日志提示，给出明确解决方法

Cookies 说明:
• 勾选「使用Cookies」后，优先级: 指定文件 > 程序同目录 cookies.json > 浏览器自动获取
• 取消勾选则使用无 Cookie 模式 (清晰度受限，720p 以下可用)
• 默认读取程序同目录的 cookies.json，无需手动指定
• 支持两种 JSON 格式:
  1. 字典格式: {{"SESSDATA": "xxx", "bili_jct": "xxx"}}
  2. 数组格式: 浏览器插件导出的 JSON 数组
• 关键字段: SESSDATA (登录凭证)、bili_jct (CSRF)
• 浏览器自动获取优先尝试 Edge，无需关闭浏览器也可读取

GitHub 项目:
• 本项目: https://github.com/FDLAlfrid/BLD

感谢使用！
"""
            dialog = self._theme_toplevel(tk.Toplevel(self.root))
            dialog.title("关于")
            dialog.geometry("540x460")
            dialog.resizable(True, True)
            dialog.minsize(440, 360)
            dialog.transient(self.root)
            dialog.grab_set()

            text_widget = tk.Text(dialog, wrap=tk.WORD, state=tk.DISABLED, font=FONT_DIALOG)
            text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            self._theme_text_widget(text_widget)
            text_widget.config(state=tk.NORMAL)
            text_widget.insert(tk.END, about_text)
            text_widget.config(state=tk.DISABLED)
            self._bind_copy_menu(text_widget)

            def open_github():
                try:
                    webbrowser.open("https://github.com/FDLAlfrid/BLD")
                except Exception:
                    pass

            btn_github = ttk.Button(dialog, text="打开 GitHub 仓库", command=open_github)
            btn_github.pack(pady=5)
            btn_close = ttk.Button(dialog, text="关闭", command=dialog.destroy)
            btn_close.pack(pady=5)
        except Exception as e:
            self._show_error("错误", f"无法打开关于对话框:\n{e}")

    def show_history(self):
        dialog = self._theme_toplevel(tk.Toplevel(self.root))
        dialog.title(f"下载历史 (共 {len(self.history)} 条)")
        dialog.geometry("720x480")
        dialog.minsize(560, 360)
        dialog.transient(self.root)
        dialog.grab_set()

        columns = ("time", "title", "bvid", "path")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", selectmode="extended")
        self._theme_treeview(tree, "History.Treeview")
        tree.heading("time", text="时间")
        tree.heading("title", text="标题")
        tree.heading("bvid", text="BV号")
        tree.heading("path", text="下载路径")
        tree.column("time", width=130, anchor=tk.W)
        tree.column("title", width=260, anchor=tk.W)
        tree.column("bvid", width=130, anchor=tk.W)
        tree.column("path", width=180, anchor=tk.W)

        vsb = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        vsb.pack(side=tk.LEFT, fill=tk.Y, pady=10)

        for idx, h in enumerate(reversed(self.history)):
            tree.insert("", tk.END, iid=str(idx), values=(
                h.get("time", ""),
                h.get("title", ""),
                h.get("bvid", ""),
                h.get("path", "")
            ))

        def _get_selected_indices():
            return [len(self.history) - 1 - int(iid) for iid in tree.selection()]

        def delete_selected():
            indices = _get_selected_indices()
            if not indices:
                self._show_info("提示", "请先选中要删除的记录", parent=dialog)
                return
            if not self._show_confirm("确认", f"确定删除选中的 {len(indices)} 条记录？", parent=dialog):
                return
            for idx in sorted(indices, reverse=True):
                if 0 <= idx < len(self.history):
                    self.history.pop(idx)
            save_history(self.history)
            dialog.destroy()
            self.show_history()

        def clear_all():
            if not self.history:
                self._show_info("提示", "历史记录已为空", parent=dialog)
                return
            if not self._show_confirm("确认", "确定清空全部下载历史？此操作不可恢复", parent=dialog):
                return
            self.history = []
            save_history(self.history)
            dialog.destroy()
            self.show_history()

        def open_selected():
            indices = _get_selected_indices()
            if not indices:
                self._show_info("提示", "请先选中要打开的记录", parent=dialog)
                return
            for idx in indices:
                if 0 <= idx < len(self.history):
                    h = self.history[idx]
                    bvid = h.get("bvid", "")
                    if bvid:
                        webbrowser.open(f"https://www.bilibili.com/video/{bvid}")

        def open_folder():
            indices = _get_selected_indices()
            if not indices:
                self._show_info("提示", "请先选中要查看的记录", parent=dialog)
                return
            for idx in indices:
                if 0 <= idx < len(self.history):
                    h = self.history[idx]
                    path = h.get("path", "")
                    if path and os.path.exists(path):
                        try:
                            os.startfile(os.path.dirname(path))
                        except Exception:
                            pass
                    else:
                        self._show_info("提示", f"文件路径不存在：{path}\n（文件可能已被移动或删除）", parent=dialog)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        ttk.Button(btn_frame, text="打开链接", command=open_selected).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="打开文件夹", command=open_folder).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Button(btn_frame, text="删除选中", command=delete_selected).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="清空全部", command=clear_all).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy).pack(fill=tk.X, pady=2)

        def on_double_click(event):
            region = tree.identify_region(event.x, event.y)
            if region == "cell":
                open_selected()
        tree.bind("<Double-1>", on_double_click)

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

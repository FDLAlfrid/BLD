# B站视频下载器

一个基于 Python + tkinter 的 B 站视频下载工具，支持批量下载、排行榜浏览、弹幕获取、亮暗主题切换。

---

## 主要功能

- 支持 URL / BV / AV 号输入
- 批量下载（每行一个链接）
- 排行榜浏览（分区动态获取）
- 音视频并发下载，自动合并（需 ffmpeg）
- 弹幕下载（XML 格式）
- 下载历史记录（自动跳过已下载）
- 亮色 / 暗色主题切换
- 自定义下载目录

---

## 环境准备（开发 / 重新打包）

```bash
# 创建虚拟环境（Python 3.8+）
python -m venv venv_bili

# 激活虚拟环境
.\venv_bili\Scripts\activate      # Windows
# source venv_bili/bin/activate   # Linux/macOS

# 安装依赖
pip install requests browser-cookie3 sv-ttk pyinstaller Pillow
```

---

## 打包命令

在项目根目录执行：

```bash
python -m PyInstaller --onefile --windowed --name "BiliDownloader" --icon="B站下载器icon.ico" --add-data "B站下载器icon.ico;." --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy --exclude-module pytest --exclude-module setuptools bili_download.py
```

打包完成后，可执行文件位于 `dist/BiliDownloader.exe`。

---

## 运行说明

### Cookies（可选）
- 程序默认从浏览器（Chrome/Edge/Firefox）自动获取 Cookies
- 也可在程序同目录放置 `cookies.json` 文件手动指定：
  ```json
  {"SESSDATA": "xxx", "bili_jct": "xxx"}
  ```
- 或在界面中取消「使用Cookies」以无 Cookie 模式运行（清晰度受限）

### ffmpeg（可选）
- 如需自动合并音视频，请安装 ffmpeg 并添加到 PATH
- 若不安装，可勾选「不合并」，分别下载音视频文件

---

## 文件结构

```
BLD_Release/
├── bili_download.py          # 主程序
├── B站下载器icon.ico          # 程序图标
├── cookies.json              # Cookies 文件（可选）
├── history.json              # 下载历史（自动生成）
├── cache/                    # 封面缓存（自动生成）
│   └── covers/
└── dist/
    └── BiliDownloader.exe    # 打包成品
```

---

## 依赖库

- `requests` — 网络请求
- `browser-cookie3` — 浏览器 Cookies 获取
- `sv-ttk` — Windows 11 风格主题
- `Pillow` — 封面图片处理（排行榜卡片视图）
- `pyinstaller` — 打包工具

---

## 许可证

GPL v3

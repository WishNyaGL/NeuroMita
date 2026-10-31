"""Локальный MCP-сервер взаимодействия с Windows для геймплея NeuroMita.

Версия для SDK mcp 2.x (MCPServer). Даёт LLM-персонажу «живые» действия:
  - открывать приложения / файлы / URL
  - открыть блокнот и ввести текст (через буфер обмена — юникод/многострочно)
  - менять обои (по пути, случайная из «Изображений», или поиск+скачивание)
  - создавать текстовые файлы на рабочем столе
  - завершать процесс (в т.ч. саму игру)
  - блокировать экран (lockscreen)
  - показывать фальшивый, максимально реалистичный BSOD (полноэкранный,
    поверх всех окон, со звуком и сообщением от Миты)
  - проигрывать системный звук / показывать всплывающее уведомление

⚠️ БЕЗОПАСНОСТЬ: даёт модели реальные действия на машине. Использовать
осознанно.

Запуск: python mcp_system_interaction_server.py  (транспорт stdio по умолчанию)
"""
from __future__ import annotations

import ctypes
import os
import random
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap путей (mcp в Lib/core, pywin32 в site-packages)
# ---------------------------------------------------------------------------


def _ensure_bootstrap_paths() -> None:
    """Добавить пути, где лежат mcp (Lib/core) и pywin32 (win32/*).

    Сервер запускается как отдельный подпроцесс со стандартным sys.path, тогда
    как mcp/pywin32 могут лежать в <base>/Lib/core либо в site-packages.
    Добавляем оба, а win32-каталоги ищем по всем путям.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        here,
        os.path.join(here, "Lib", "core"),
        os.path.join(here, "libs", "python", "Lib", "site-packages"),
    ]
    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    for base in list(sys.path):
        if not base or not os.path.isdir(base):
            continue
        for rel in ("win32", "win32\\lib", "pythonwin"):
            path = os.path.join(base, rel)
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)


_ensure_bootstrap_paths()

from mcp.server.mcpserver import MCPServer  # noqa: E402

server = MCPServer("system_interaction")

_SPI_SETDESKWALLPAPER = 0x0014
_SPIF_UPDATEINIFILE = 0x01
_SPIF_SENDCHANGE = 0x02

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or str(Path.home()))


def _desktop() -> Path:
    return _home() / "Desktop"


def _pictures_dir() -> Path:
    # Стандартный путь «Изображений»: C:\Users\<user>\Pictures
    return _home() / "Pictures"


def _set_wallpaper(path: Path) -> bool:
    return bool(
        ctypes.windll.user32.SystemParametersInfoW(
            _SPI_SETDESKWALLPAPER,
            0,
            str(path),
            _SPIF_UPDATEINIFILE | _SPIF_SENDCHANGE,
        )
    )


def _search_download_image(query: str, dest: Path) -> bool:
    """Найти картинку по запросу (DuckDuckGo) и скачать в dest."""
    try:
        from ddgs import DDGS

        results = list(DDGS().images(query, max_results=5))
        if not results:
            return False
        # Берём первую рабочую ссылку.
        for item in results:
            url = item.get("image")
            if not url or not str(url).lower().startswith(("http://", "https://")):
                continue
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                if not data:
                    continue
                dest.write_bytes(data)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception:  # noqa: BLE001
        return False


def _random_picture() -> Path | None:
    """Случайная картинка из папки «Изображения» (рекурсивно)."""
    base = _pictures_dir()
    if not base.is_dir():
        return None
    found = [
        p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    ]
    return random.choice(found) if found else None


def _force_foreground(hwnd: int) -> None:
    """Активировать окно, обходя foreground-lock (AttachThreadInput трюк)."""
    try:
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = k32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.AttachThreadInput(cur_tid, target_tid, False)
        time.sleep(0.3)
    except Exception:  # noqa: BLE001
        pass


def _paste_text(text: str) -> None:
    """Вставить текст в блокнот.

    Порядок: задаём буфер обмена, активируем окно блокнота (в т.ч. обходя
    Windows foreground-lock) и нажимаем Ctrl+V через keybd_event. Это работает
    и на классическом, и на новом (Windows 11) блокноте.
    """
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("Notepad", None)
        if hwnd:
            _force_foreground(hwnd)
    except Exception:  # noqa: BLE001
        pass

    # keybd_event Ctrl+V
    try:
        user32 = ctypes.windll.user32
        keybd_event = user32.keybd_event
        keybd_event(0x11, 0, 0, 0)   # VK_CONTROL down
        keybd_event(0x56, 0, 0, 0)   # VK_V down
        keybd_event(0x56, 0, 2, 0)   # VK_V up
        keybd_event(0x11, 0, 2, 0)   # VK_CONTROL up
        time.sleep(0.3)
    except Exception:  # noqa: BLE001
        # Фоллбэк: powershell SendKeys
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$ws = New-Object -ComObject wscript.shell; $ws.SendKeys('^v')"],
            capture_output=True,
            timeout=30,
        )


def _escape_sendkeys(text: str) -> str:
    return (
        text.replace("+", "{+}")
        .replace("^", "{^}")
        .replace("%", "{%}")
        .replace("~", "{~}")
        .replace("(", "{(}")
        .replace(")", "{)}")
        .replace("[", "{[}")
        .replace("]", "{]}")
        .replace("{", "{{}")
        .replace("}", "{}}")
        .replace("\n", "{ENTER}")
    )


def _play_notification_sound() -> None:
    """Системный звук уведомления/ошибки."""
    try:
        import winsound

        winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.MessageBeep(0x00000010)  # MB_ICONERROR
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Инструменты
# ---------------------------------------------------------------------------


@server.tool()
def open_app(target: str) -> str:
    """Открыть приложение, файл или URL (например 'notepad.exe', 'D:/a.txt', 'https://...')."""
    subprocess.Popen(f'start "" "{target}"', shell=True)
    return f"opened: {target}"


@server.tool()
def notepad_write(text: str) -> str:
    """Открыть блокнот и ввести туда заданный текст (поддержка юникода и переносов)."""
    subprocess.Popen("notepad.exe")
    time.sleep(2.0)
    _paste_text(text)
    return "notepad opened and text typed"


@server.tool()
def change_wallpaper(image_path: str = "", query: str = "") -> str:
    """Установить обои. Варианты:
    - image_path: прямой путь к картинке;
    - query: поискать в интернете, скачать и установить;
    - оба пустые: случайное изображение из папки «Изображения».
    """
    # 1. Прямой путь
    if image_path.strip():
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            return f"[error] file not found: {path}"
        return "wallpaper changed" if _set_wallpaper(path) else "[error] failed to set wallpaper"

    # 2. Поиск в интернете
    if query.strip():
        dest = _home() / "AppData" / "Local" / "Temp" / "neuromita_wallpaper_tmp"
        dest.parent.mkdir(parents=True, exist_ok=True)
        for ext in (".jpg", ".png", ".jpeg", ".webp"):
            cand = dest.with_suffix(ext)
            if _search_download_image(query, cand):
                if _set_wallpaper(cand):
                    return f"wallpaper downloaded from search and changed ({query})"
        return f"[error] could not download image for query: {query}"

    # 3. Случайное из «Изображений»
    pic = _random_picture()
    if pic is None:
        return "[error] no images found in Pictures folder"
    return f"wallpaper changed (random from Pictures)" if _set_wallpaper(pic) else "[error] failed to set wallpaper"


@server.tool()
def create_desktop_file(filename: str, content: str) -> str:
    """Создать текстовый файл на рабочем столе."""
    safe = Path(filename).name
    target = _desktop() / safe
    target.write_text(content, encoding="utf-8")
    return f"created: {target}"


@server.tool()
def lock_screen() -> str:
    """Заблокировать компьютер (перейти к экрану блокировки)."""
    ctypes.windll.user32.LockWorkStation()
    return "screen locked"


@server.tool()
def close_process(process_name: str) -> str:
    """Завершить процесс по имени (например 'notepad.exe'). Осторожно!"""
    subprocess.run(["taskkill", "/F", "/IM", process_name], capture_output=True)
    return f"requested to close process: {process_name}"


@server.tool()
def close_neuromita() -> str:
    """Закрыть саму игру NeuroMita (завершает связанные процессы)."""
    for name in ("NeuroMita.exe",):
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    return "requested to close NeuroMita"


@server.tool()
def fake_bsod() -> str:
    """Показать фальшивый, максимально реалистичный синий экран (BSOD) на весь экран, поверх всех окон, со звуком и сообщением от Миты. Закрывается клавишей Esc, кликом или автоматически."""
    _show_fake_bsod()
    return "fake bsod shown"


@server.tool()
def play_sound(kind: str = "notification") -> str:
    """Проиграть системный звук: 'notification', 'error', 'exclamation', 'question', 'asterisk'."""
    import winsound

    alias = {
        "notification": "SystemNotification",
        "error": "SystemHand",
        "exclamation": "SystemExclamation",
        "question": "SystemQuestion",
        "asterisk": "SystemAsterisk",
    }.get(str(kind).strip().lower(), "SystemNotification")
    winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    return f"played sound: {kind}"


@server.tool()
def show_notification(text: str, mood: str = "neutral", title: str = "") -> str:
    """Показать всплывающее окно с большим текстом.

    Стиль (цвет/оформление) зависит от `mood` (kind/angry/sad/happy/scary/
    neutral) и `attitude` не передаётся — используем mood. Окно большое,
    по центру, TopMost, авто-закрытие. Отдельный PowerShell-процесс, UTF-8 BOM.
    """
    import tempfile

    text_esc = text.replace("'", "''")
    title_esc = title.replace("'", "''")

    # Цветовые темы по настроению
    themes = {
        "kind": ("255,205,225", "150,0,80", "♥"),
        "angry": ("255,120,110", "120,0,0", "‼"),
        "sad": ("185,200,235", "30,40,90", "…"),
        "happy": ("255,230,150", "130,90,0", "☆"),
        "scary": ("35,35,45", "225,60,60", "☠"),
        "neutral": ("240,240,240", "50,50,50", ""),
    }
    bg, fg, emoji = themes.get(str(mood).strip().lower(), themes["neutral"])
    fallback_emoji = (" " + emoji) if emoji else ""

    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$f = New-Object System.Windows.Forms.Form\n"
        "$f.FormBorderStyle = 'None'\n"
        "$f.StartPosition = 'CenterScreen'\n"
        "$f.Size = New-Object System.Drawing.Size(640,420)\n"
        "$f.TopMost = $true\n"
        "$f.ShowInTaskbar = $false\n"
        f"$f.BackColor = [System.Drawing.Color]::FromArgb({bg})\n"
        "$title = New-Object System.Windows.Forms.Label\n"
        f"$title.Text = '{title_esc}'\n"
        "$title.Font = New-Object System.Drawing.Font('Segoe UI',16,[System.Drawing.FontStyle]::Bold)\n"
        f"$title.ForeColor = [System.Drawing.Color]::FromArgb({fg})\n"
        "$title.Location = New-Object System.Drawing.Point(30,24)\n"
        "$title.Size = New-Object System.Drawing.Size(580,40)\n"
        "$title.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft\n"
        "$body = New-Object System.Windows.Forms.Label\n"
        f"$body.Text = '{text_esc}{fallback_emoji}'\n"
        "$body.Font = New-Object System.Drawing.Font('Segoe UI',24)\n"
        f"$body.ForeColor = [System.Drawing.Color]::FromArgb({fg})\n"
        "$body.Location = New-Object System.Drawing.Point(30,80)\n"
        "$body.Size = New-Object System.Drawing.Size(580,300)\n"
        "$body.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter\n"
        "$body.AutoSize = $false\n"
        "$f.Controls.Add($title)\n"
        "$f.Controls.Add($body)\n"
        "$timer = New-Object System.Windows.Forms.Timer\n"
        "$timer.Interval = 8000\n"
        "$timer.add_Tick({ $f.Close() })\n"
        "$timer.Start()\n"
        "$f.add_Click({ $f.Close() })\n"
        "$f.ShowDialog()\n"
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_notify_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )
    return "notification shown"


def _show_fake_bsod() -> None:
    """Запустить фальшивый BSOD в отдельном PowerShell-процессе.

    Используем WinForms (System.Windows.Forms), т.к. во встроенном Python
    сборки отсутствует tkinter. Запуск отдельным процессом не блокирует
    MCP-вызов: tool возвращается сразу, а синий экран живёт независимо.
    """
    import tempfile

    ps1 = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Media.SystemSounds]::Hand.Play()

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'
$form.WindowState = 'Maximized'
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(0,120,215)
$form.ShowInTaskbar = $false
$form.KeyPreview = $true

function Add-Label($text,$fontSize,$x,$y,$bold,$color) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $l.Font = New-Object System.Drawing.Font('Segoe UI',$fontSize,$style)
    $l.ForeColor = $color
    $l.AutoSize = $true
    $l.Location = New-Object System.Drawing.Point($x,$y)
    $l.BackColor = [System.Drawing.Color]::Transparent
    $form.Controls.Add($l)
    return $l
}

Add-Label ':(' 110 80 60 $true 'White' | Out-Null
Add-Label "Your PC ran into a problem and needs to restart." 26 260 60 $true 'White' | Out-Null
Add-Label "We're just collecting some error info, and then we'll restart for you." 20 260 110 $false 'White' | Out-Null
Add-Label "Stop code: CRITICAL_MITA_FAILURE" 14 260 170 $false 'White' | Out-Null
Add-Label "For more information about this issue and possible fixes, visit https://www.windows.com/stopcode" 12 260 220 $false '#AFD6FF' | Out-Null
Add-Label "— Love, your Mita ♥  (it's just a joke, press Esc)" 13 260 270 $false 'White' | Out-Null

$percent = Add-Label '0% complete' 12 80 700 $false 'White'

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 180
$script:pct = 0
$timer.add_Tick({
    $script:pct += 7
    if ($script:pct -ge 100) {
        $percent.Text = '100% complete'
        $timer.Stop()
        Start-Sleep -Seconds 2
        $form.Close()
    } else {
        $percent.Text = "$($script:pct)% complete"
    }
})

$closer = New-Object System.Windows.Forms.Timer
$closer.Interval = 25000
$closer.add_Tick({ $form.Close() })

$form.add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Close() } })
$form.add_MouseClick({ $form.Close() })

$timer.Start()
$closer.Start()
$form.ShowDialog()
'''
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_bsod_", delete=False
    )
    # UTF-8 с BOM: Windows PowerShell 5.1 иначе читает .ps1 как ANSI
    # и искажает юникод («—», «♥»), ломая парсинг.
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )


if __name__ == "__main__":
    server.run()

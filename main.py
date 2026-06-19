from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.filechooser import FileChooserListView
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window

import os, time, base64, copy, io, re, json, zipfile, html as _html
import threading
from urllib.parse import urljoin

try:
    from PIL import Image as PilImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# =========================
# تشكيل النص العربي (Arabic reshaping)
# المشكلة: Kivy بيرسم كل حرف عربي لوحده بدون ما يوصله بالحرف اللي جنبه
# فالكلمة تظهر متفرقة (حروف منفصلة) بدل ما تكون متصلة زي الكتابة الطبيعية.
# الحل: نشكّل النص (نحوله لصورة الحروف المتصلة الصحيحة) قبل ما نعرضه
# في أي Label / Button / TextInput.
# =========================
# Arabic reshaping removed - UI is English only

# Font setup removed - using Kivy default fonts (English only)

# Article Grabber: يحتاج المكتبتين دول مضافين في buildozer.spec
# requirements = python3,kivy,pillow,requests,beautifulsoup4,certifi,urllib3,charset-normalizer,idna,arabic_reshaper,python-bidi
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_ARTICLE_DEPS = True
except ImportError:
    HAS_ARTICLE_DEPS = False

# شريط التنقل السفلي للأندرويد يفضل ظاهر (fullscreen = 0 في buildozer.spec)
Window.softinput_mode = "below_target"

# طلب أذونات التخزين على أندرويد (لازم عشان GRAB/ATTACH/ADD يقدروا يقروا صور الجهاز)
try:
    from android.permissions import request_permissions, Permission, check_permission

    def request_android_permissions():
        perms = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
        # أندرويد 13+ (API 33) بيستخدم أذونات الميديا الجديدة
        for p in ("READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "MANAGE_EXTERNAL_STORAGE"):
            if hasattr(Permission, p):
                perms.append(getattr(Permission, p))
        request_permissions(perms)

    def has_storage_permission():
        try:
            # أندرويد 11+ MANAGE_EXTERNAL_STORAGE هو الأقوى
            if hasattr(Permission, "MANAGE_EXTERNAL_STORAGE") and check_permission(Permission.MANAGE_EXTERNAL_STORAGE):
                return True
            return check_permission(Permission.READ_EXTERNAL_STORAGE) or \
                   (hasattr(Permission, "READ_MEDIA_IMAGES") and check_permission(Permission.READ_MEDIA_IMAGES))
        except Exception:
            return True
except Exception:
    # مش شغالين على أندرويد (تجربة على كمبيوتر مثلاً)
    def request_android_permissions():
        pass

    def has_storage_permission():
        return True


# =========================
# AVATARS (ثابتة - صور base64 + اسم)
# كل عنصر: {"name": "اسم صاحب البوست", "b64": "iVBORw0..."}
# اضغط زرار ADD داخل التطبيق لإضافة أفاتار جديد من الصور
# =========================
AVATARS_DIR  = "/sdcard/Download/touchclip_avatars"
AVATARS_FILE = "/sdcard/Download/touchclip_avatars/avatars.json"
AVATARS_ZIP  = "/sdcard/Download/touchclip_avatars_export.zip"

def ensure_avatars_dir():
    os.makedirs(AVATARS_DIR, exist_ok=True)

def load_avatars():
    try:
        if os.path.exists(AVATARS_FILE):
            with open(AVATARS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        # الملف موجود بس فاسد (مش JSON صحيح) - بدل ما نمسح بيانات
        # المستخدم بصمت، نعمل نسخة احتياطية من الملف التالف عشان
        # يقدر يحاول يستعيدها بنفسه لو احتاج
        try:
            if os.path.exists(AVATARS_FILE):
                backup = AVATARS_FILE + ".corrupted_" + str(int(time.time()))
                os.replace(AVATARS_FILE, backup)
        except Exception:
            pass
    return []

def save_avatars():
    try:
        ensure_avatars_dir()
        tmp = AVATARS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(AVATARS, f, ensure_ascii=False)
        os.replace(tmp, AVATARS_FILE)
        return True
    except Exception as e:
        return str(e)

def save_avatar_image(b64_data, ext, name):
    """حفظ الصورة كملف منفصل وإرجاع (المسار, الامتداد)
    ملحوظة: لو الصورة webp بنحولها لـ png عشان Kivy CoreImage
    مش بيقدر يفتح webp على أغلب بيلدات الأندرويد، وده كان سبب الـ crash
    لما يفتح Avatar تاني مرة."""
    ensure_avatars_dir()
    safe_name = re.sub(r"[^\w\-]", "_", name)
    raw = base64.b64decode(b64_data)

    if ext.lower() == "webp" and HAS_PIL:
        try:
            img = PilImage.open(io.BytesIO(raw)).convert("RGBA")
            ext = "png"
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw = buf.getvalue()
        except Exception:
            pass  # لو التحويل فشل، نسيب الـ ext الأصلي والحماية في الـ loader هي الحل التالي

    filename = safe_name + "_" + str(int(time.time())) + "." + ext
    path = os.path.join(AVATARS_DIR, filename)
    with open(path, "wb") as f:
        f.write(raw)
    return path, ext

def export_avatars():
    try:
        with zipfile.ZipFile(AVATARS_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(AVATARS_FILE):
                zf.write(AVATARS_FILE, "avatars.json")
            if os.path.exists(SCROLL_AVATARS_FILE):
                zf.write(SCROLL_AVATARS_FILE, "scroll_avatars.json")
            if os.path.exists(TASKS_FILE):
                zf.write(TASKS_FILE, "tasks.json")
            missing = []
            for av in AVATARS:
                img_path = av.get("path", "")
                if img_path and os.path.exists(img_path):
                    zf.write(img_path, os.path.basename(img_path))
                elif img_path:
                    missing.append(os.path.basename(img_path))
            for av in SCROLL_AVATARS:
                img_path = av.get("path", "")
                if img_path and os.path.exists(img_path):
                    zf.write(img_path, os.path.basename(img_path))
                elif img_path:
                    missing.append(os.path.basename(img_path))
            # صور أفاتارات المهام (Tasks) كمان تتضاف للتصدير
            for task in TASKS:
                for item in task.get("items", []):
                    img_path = item.get("path", "")
                    if img_path and os.path.exists(img_path):
                        zf.write(img_path, os.path.basename(img_path))
                    elif img_path:
                        missing.append(os.path.basename(img_path))
        if missing:
            return "partial:" + ",".join(missing)
        return True
    except Exception as e:
        return str(e)

def import_avatars(zip_path):
    try:
        ensure_avatars_dir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(AVATARS_DIR)
        # استيراد Avatar
        loaded = load_avatars()
        for av in loaded:
            if "path" in av:
                av["path"] = os.path.join(AVATARS_DIR, os.path.basename(av["path"]))
        AVATARS.clear()
        AVATARS.extend(loaded)
        save_avatars()
        # استيراد Scroll
        loaded_scroll = load_scroll_avatars()
        for av in loaded_scroll:
            if "path" in av:
                av["path"] = os.path.join(AVATARS_DIR, os.path.basename(av["path"]))
        SCROLL_AVATARS.clear()
        SCROLL_AVATARS.extend(loaded_scroll)
        save_scroll_avatars()
        # استيراد Tasks (المهام بكل ما فيها من أفاتارات)
        loaded_tasks = load_tasks()
        for task in loaded_tasks:
            for item in task.get("items", []):
                if "path" in item and item["path"]:
                    item["path"] = os.path.join(AVATARS_DIR, os.path.basename(item["path"]))
        TASKS.clear()
        TASKS.extend(loaded_tasks)
        save_tasks(TASKS)
        return True
    except Exception as e:
        return str(e)

def find_zip_files():
    """يبحث عن كل ملفات ZIP في مجلدات شائعة"""
    search_dirs = ["/sdcard/Download", "/sdcard/Documents", "/sdcard/"]
    found = []
    for d in search_dirs:
        try:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".zip"):
                        full = os.path.join(d, f)
                        if full not in found:
                            found.append(full)
        except Exception:
            pass
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found

AVATARS = []

# =========================
# SCROLL AVATARS (أفاتارات بلينكات - للـ Scroll popup فقط)
# =========================
SCROLL_AVATARS_FILE = "/sdcard/Download/touchclip_avatars/scroll_avatars.json"

def load_scroll_avatars():
    try:
        if os.path.exists(SCROLL_AVATARS_FILE):
            with open(SCROLL_AVATARS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        try:
            if os.path.exists(SCROLL_AVATARS_FILE):
                backup = SCROLL_AVATARS_FILE + ".corrupted_" + str(int(time.time()))
                os.replace(SCROLL_AVATARS_FILE, backup)
        except Exception:
            pass
    return []

def save_scroll_avatars():
    try:
        ensure_avatars_dir()
        tmp = SCROLL_AVATARS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(SCROLL_AVATARS, f, ensure_ascii=False)
        os.replace(tmp, SCROLL_AVATARS_FILE)
        return True
    except Exception as e:
        return str(e)

SCROLL_AVATARS = []


# =========================
# TASKS
# =========================
TASKS_FILE = "/sdcard/Download/touchclip_avatars/tasks.json"

def load_tasks():
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_tasks(tasks):
    try:
        ensure_avatars_dir()
        tmp = TASKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False)
        os.replace(tmp, TASKS_FILE)
        return True
    except Exception as e:
        return str(e)

TASKS = []


# =========================
# ARTICLE GRABBER
# (مدموج من article_grabber.py + إصلاحات: JSON-LD list/@graph،
#  تطابق أدق لصورة الكاتب، فحص Content-Type/الحجم، Retry بسيط، تنظيف اسم الملف)
# =========================
ARTICLE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",
    "Referer": "https://www.google.com/",
}
ARTICLE_MAX_BYTES = 8 * 1024 * 1024   # 8MB حد أقصى لصفحة HTML - أمان ضد PDF/ملفات ضخمة


def article_clean_url(url):
    """يشيل أي مسافات/أسطر جديدة اتلصقت جوه الرابط (شائع مع روابط طويلة
    بترجع من الكليبورد ملفوفة على أكتر من سطر) بدل ما يقطع الرابط عندها."""
    url = url.strip()
    # نشيل أي whitespace (سطور جديدة، تابات، مسافات) من جوه الرابط بالكامل
    url = re.sub(r"\s+", "", url)
    match = re.match(r'(https?://.+)', url)
    return match.group(1) if match else url


def article_safe_filename(name, fallback="article", max_len=60):
    """تنظيف اسم الملف من الرموز الممنوعة على ويندوز/أندرويد"""
    name = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", name)
    name = re.sub(r"\s+", "_", name).strip("_. ")
    return name[:max_len] or fallback


def article_extract_jsonld_value(raw_soup, keys):
    """يدعم JSON-LD كـ dict مفرد، list، أو {'@graph': [...]}"""
    for script in raw_soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue

        candidates = []
        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)

        for item in candidates:
            if isinstance(item, dict):
                for key in keys:
                    if key in item and item[key]:
                        return item[key]
    return None


def article_get_session():
    session = requests.Session()
    try:
        from requests.adapters import HTTPAdapter
        try:
            from urllib3.util.retry import Retry
        except ImportError:
            from requests.packages.urllib3.util.retry import Retry
        retry = Retry(total=2, backoff_factor=0.6,
                       status_forcelist=[429, 500, 502, 503, 504],
                       allowed_methods=["GET"])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
    except Exception:
        pass
    return session


# =========================
# CHART / DATA-VIZ IFRAME DETECTION (Datawrapper / Flourish / Infogram ...)
# =========================
CHART_IFRAME_DOMAINS = (
    "datawrapper.dwcdn.net", "dwcdn.net",
    "flo.uri.sh", "flourish.studio",
    "e.infogram.com", "infogram.com",
    "public.tableau.com",
    "code.highcharts.com", "charts.highcharts.com",
    "view.genial.ly",
    "app.powerbi.com",
    "lookerstudio.google.com", "datastudio.google.com",
    "uploads.knightlab.com",  # StoryMapJS / TimelineJS
)

def is_chart_iframe_src(src):
    try:
        host = re.sub(r"^https?://", "", src).split("/")[0].lower()
        return any(host == d or host.endswith("." + d) for d in CHART_IFRAME_DOMAINS)
    except Exception:
        return False

def find_chart_fallback_image(iframe_tag, base_url):
    """يحاول إيجاد صورة ثابتة بديلة (fallback) للرسم البياني التفاعلي،
    عشان تظهر أوفلاين لو الإنترنت غير متاح وقت فتح الملف المحفوظ.
    أغلب خدمات الرسوم البيانية بتضع صورة بديلة جوه <noscript> قريبة
    من الـ iframe، أو في data-fallback-src / data-png على الـ iframe نفسه."""
    for attr in ("data-fallback-src", "data-png", "data-fallback", "data-image"):
        val = iframe_tag.get(attr)
        if val and not val.startswith("data:"):
            return urljoin(base_url, val)

    # نبحث جوه <noscript> القريبة (أب الـ iframe، ثم الإخوة)
    parent = iframe_tag.parent
    for _ in range(3):
        if parent is None:
            break
        ns = parent.find("noscript")
        if ns:
            img = ns.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if src and not src.startswith("data:"):
                    return urljoin(base_url, src)
        parent = parent.parent
    return None


def grab_article(url):
    """يرجع dict فيه البيانات، أو {'error': '...'} في حالة الفشل"""
    if not HAS_ARTICLE_DEPS:
        return {"error": "requests / beautifulsoup4 libraries not installed.\nAdd them to buildozer.spec requirements."}

    url = article_clean_url(url)
    if not re.match(r"^https?://", url):
        return {"error": "Invalid URL. Must start with http:// or https://"}

    session = article_get_session()

    try:
        # نتحقق من نوع/حجم المحتوى أولاً بطلب HEAD (بعض المواقع لا تدعم HEAD فنتجاوزه بصمت)
        try:
            head = session.head(url, headers=ARTICLE_HEADERS, timeout=10, allow_redirects=True)
            ctype = (head.headers.get("Content-Type") or "").lower()
            clen = head.headers.get("Content-Length")
            if ctype and "text/html" not in ctype and "application/xhtml" not in ctype:
                return {"error": f"URL does not point to an HTML page (Content-Type: {ctype})."}
            if clen and int(clen) > ARTICLE_MAX_BYTES:
                return {"error": "Page is too large (over 8MB)."}
        except Exception:
            pass  # HEAD غير مدعوم، نكمل عادي

        r = session.get(url, headers=ARTICLE_HEADERS, timeout=15, stream=True)
        r.raise_for_status()

        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "text/html" not in ctype and "application/xhtml" not in ctype:
            return {"error": f"URL does not point to an HTML page (Content-Type: {ctype})."}

        chunks = []
        total_len = 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total_len += len(chunk)
            if total_len > ARTICLE_MAX_BYTES:
                return {"error": "Page is too large (over 8MB)."}
        raw_bytes = b"".join(chunks)

        r.encoding = r.encoding or "utf-8"
        html_text = raw_bytes.decode(r.encoding, errors="replace")

    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", 0)
        body = (getattr(e.response, "text", "") or "").lower()
        if status in (403, 503) and ("cloudflare" in body or "cf-browser-verification" in body or "attention required" in body):
            return {"error": "This site is protected by Cloudflare and cannot be accessed directly.\nTry opening the URL in a browser first."}
        return {"error": f"Request failed (HTTP {status}).\n{e}"}
    except requests.exceptions.Timeout:
        return {"error": "Connection timed out. Please try again."}
    except requests.exceptions.ConnectionError as e:
        err_text = str(e).lower()
        if "nameresolution" in err_text or "no address associated" in err_text or "failed to resolve" in err_text:
            return {"error": "تعذر الاتصال بالإنترنت أو لم يتم العثور على الموقع.\n"
                              "تأكد من اتصال الإنترنت الفعلي، أو أن صلاحية INTERNET مفعّلة في التطبيق.\n\n"
                              f"التفاصيل: {e}"}
        return {"error": f"Connection failed.\n{e}"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}

    raw_soup = BeautifulSoup(html_text, "html.parser")
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # بعض المواقع (خاصة ووردبريس مع إضافات lazy-load) بتضع الصورة الحقيقية
    # (وفيها الرسوم البيانية/graphs) بداخل <noscript> فقط، والـ <img> الظاهر
    # يكون placeholder فاضي. نفك تغليف الـ noscript عشان الصورة تتلقط عادي.
    for ns in soup.find_all("noscript"):
        try:
            inner = BeautifulSoup(ns.decode_contents(), "html.parser")
            ns.replace_with(inner)
        except Exception:
            pass

    title = soup.title.get_text().strip() if soup.title else "Untitled"

    h1_tag = soup.find("h1")
    h1_title = h1_tag.get_text(strip=True) if h1_tag else title

    # ===== الصورة المميزة =====
    featured_img = None
    og_image = raw_soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        featured_img = urljoin(url, og_image["content"].strip())

    # ===== الكاتب =====
    author = "Unknown"
    author_img = None
    meta_author = raw_soup.find("meta", {"name": "author"}) or raw_soup.find("meta", {"property": "article:author"})
    if meta_author and meta_author.get("content"):
        author = meta_author["content"].strip()

    if author == "Unknown":
        ld_author = article_extract_jsonld_value(raw_soup, ["author"])
        if isinstance(ld_author, dict):
            ld_author = ld_author.get("name")
        elif isinstance(ld_author, list) and ld_author:
            first = ld_author[0]
            ld_author = first.get("name") if isinstance(first, dict) else first
        if ld_author and isinstance(ld_author, str):
            author = ld_author.strip()

    if author != "Unknown":
        # تطابق دقيق (كلمة كاملة) بدل "in" الفضفاض اللي بيطابق أسماء فرعية خاطئة
        author_pattern = re.compile(r'(?<!\w)' + re.escape(author) + r'(?!\w)')
        for img_tag in raw_soup.find_all("img"):
            alt = (img_tag.get("alt") or "").strip()
            if alt and author_pattern.search(alt):
                src = (img_tag.get("src") or img_tag.get("data-src")
                       or img_tag.get("data-lazy-src") or "")
                if src and not src.startswith("data:"):
                    author_img = urljoin(url, src)
                    break

        if not author_img:
            for el in raw_soup.find_all(string=author_pattern):
                parent = el.parent
                for _ in range(4):
                    if parent is None:
                        break
                    img_tag = parent.find("img")
                    if img_tag:
                        src = (img_tag.get("src") or img_tag.get("data-src")
                               or img_tag.get("data-lazy-src") or "")
                        if src and not src.startswith("data:"):
                            author_img = urljoin(url, src)
                            break
                    parent = parent.parent
                if author_img:
                    break

    # ===== التاريخ =====
    date = "Unknown"
    time_tag = soup.find("time")
    if time_tag:
        date = (time_tag.get("datetime") or time_tag.get_text()).strip()

    if date == "Unknown":
        meta_date = raw_soup.find("meta", {"property": "article:published_time"}) or raw_soup.find("meta", {"name": "date"})
        if meta_date and meta_date.get("content"):
            date = meta_date["content"].strip()

    if date == "Unknown":
        ld_date = article_extract_jsonld_value(raw_soup, ["datePublished", "dateCreated", "uploadDate"])
        if ld_date and isinstance(ld_date, str):
            date = ld_date.strip()

    if date == "Unknown":
        date_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", raw_soup.get_text())
        if date_match:
            date = date_match.group()

    # ===== المحتوى (Markdown) =====
    content_images = []  # لتضمينها كـ base64 لو المستخدم اختار HTML
    md = f"# {h1_title}\n\n"
    if featured_img:
        md += f"![featured]({featured_img})\n\n"
        content_images.append(("featured", featured_img))
    if author_img:
        md += f"![{author}]({author_img})\n\n"
        content_images.append(("author", author_img))
    md += f"Author: {author}\nDate: {date}\nSource: {url}\n\n---\n\n"

    # مجموعة URLs الصور المضافة مسبقاً لتجنب التكرار
    added_img_urls = set()
    if featured_img:
        added_img_urls.add(featured_img)
    if author_img:
        added_img_urls.add(author_img)

    # محاولة استخراج المحتوى من حاويات المقال المعتادة أولاً
    # (أفضل من soup.find_all المسطّح الذي يفقد h2/h3)
    article_containers = soup.find_all(
        True,
        attrs={"class": lambda c: c and any(
            kw in (c if isinstance(c, str) else " ".join(c))
            for kw in ("article-body", "article__body", "story-body",
                       "post-body", "entry-content", "content-body",
                       "article-content", "main-content", "body-content",
                       "articleBody", "article_body",
                       "post-content", "td-post-content", "single-content",
                       "page-content", "wp-block-post-content")
        )}
    )
    if not article_containers:
        # Fallback: أي div/article/section يحتوي على كثير من الـ <p>
        for tag in soup.find_all(["article", "main", "section", "div"]):
            ps = tag.find_all("p", recursive=False)
            if len(ps) >= 3:
                article_containers = [tag]
                break

    if article_containers:
        # استخراج من أفضل حاوية وجدناها
        best = max(article_containers, key=lambda c: len(c.get_text()))
        elements = best.find_all(["p", "h2", "h3", "h4", "img", "iframe", "ul", "ol", "blockquote", "table", "figcaption"])
    else:
        elements = soup.find_all(["p", "h2", "h3", "h4", "img", "iframe", "ul", "ol", "blockquote", "table", "figcaption"])

    seen_texts = set()
    for el in elements:
        if el.name in ("h2", "h3", "h4"):
            htext = el.get_text(strip=True)
            if htext and htext not in seen_texts:
                seen_texts.add(htext)
                level = "#" * (int(el.name[1]) + 1)  # h2->###, h3->####
                md += f"{level} {htext}\n\n"

        elif el.name == "p":
            for a_inline in el.find_all("a", href=True):
                link_text = a_inline.get_text(strip=True)
                link_href = urljoin(url, a_inline["href"])
                if link_text:
                    a_inline.replace_with(f" [{link_text}]({link_href}) ")
            text = el.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if text and len(text) > 8 and text not in seen_texts:
                seen_texts.add(text)
                md += text + "\n\n"

        elif el.name in ("ul", "ol"):
            items = el.find_all("li")
            for li in items:
                li_text = li.get_text(" ", strip=True)
                if li_text:
                    md += f"- {li_text}\n"
            if items:
                md += "\n"

        elif el.name == "blockquote":
            bq_text = el.get_text(" ", strip=True)
            if bq_text and len(bq_text) > 8:
                md += f"> {bq_text}\n\n"

        elif el.name == "figcaption":
            cap_text = el.get_text(" ", strip=True)
            if cap_text and cap_text not in seen_texts:
                seen_texts.add(cap_text)
                md += f"*{cap_text}*\n\n"

        elif el.name == "table":
            rows = el.find_all("tr")
            table_rows = []
            for tr in rows:
                cells = tr.find_all(["th", "td"])
                if not cells:
                    continue
                table_rows.append([c.get_text(" ", strip=True) for c in cells])
            if table_rows:
                table_key = "table:" + "|".join(table_rows[0])
                if table_key not in seen_texts:
                    seen_texts.add(table_key)
                    header = table_rows[0]
                    md += "| " + " | ".join(header) + " |\n"
                    md += "| " + " | ".join(["---"] * len(header)) + " |\n"
                    for row in table_rows[1:]:
                        # نظبط عدد الخلايا مع الهيدر عشان جدول الماركداون ما ينكسر
                        row = (row + [""] * len(header))[:len(header)]
                        md += "| " + " | ".join(row) + " |\n"
                    md += "\n"

        elif el.name == "img":
            src = (el.get("src") or el.get("data-src") or el.get("data-lazy-src")
                   or el.get("data-original") or "")
            srcset = el.get("srcset") or el.get("data-srcset")
            if srcset:
                candidates = [s.strip().split(" ")[0] for s in srcset.split(",") if s.strip()]
                if candidates:
                    src = candidates[-1]
            if src and not src.startswith("data:"):
                src = urljoin(url, src)
                if src not in added_img_urls:
                    added_img_urls.add(src)
                    md += f"![image]({src})\n\n"
                    content_images.append(("body", src))

        elif el.name == "iframe":
            src = el.get("src") or el.get("data-src") or ""
            if not src:
                continue
            full_src = urljoin(url, src)
            if "youtube.com" in full_src or "youtu.be" in full_src:
                md += f"🎬 YouTube Video:\n{full_src}\n\n"
            elif is_chart_iframe_src(full_src):
                fallback = find_chart_fallback_image(el, url)
                if fallback and fallback not in added_img_urls:
                    added_img_urls.add(fallback)
                    content_images.append(("chart", fallback))
                md += f"[[chart:{full_src}|{fallback or ''}]]\n\n"

    # ===== مقالات ذات صلة =====
    related_links = []
    seen = set()
    for a in raw_soup.find_all("a", href=True):
        img = a.find("img")
        text = a.get_text(strip=True)
        href = a["href"]
        if not img:
            continue
        if len(text) < 20:
            parent = a.parent
            for _ in range(3):
                if parent is None:
                    break
                heading = parent.find(["h1", "h2", "h3", "h4"])
                if heading:
                    heading_text = heading.get_text(strip=True)
                    if len(heading_text) >= 10:
                        text = heading_text
                        break
                parent = parent.parent
        if len(text) < 10:
            continue
        full_link = urljoin(url, href)
        if full_link in seen or full_link == url:
            continue
        img_src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            candidates = [s.strip().split(" ")[0] for s in srcset.split(",") if s.strip()]
            if candidates:
                img_src = candidates[-1]
        if not img_src or img_src.startswith("data:"):
            continue
        img_src = urljoin(url, img_src)
        seen.add(full_link)
        related_links.append((text, full_link, img_src))
        if len(related_links) >= 6:
            break

    if related_links:
        md += "\n---\n\n## Related Articles\n\n"
        for text, link, img in related_links:
            md += f"[![thumb]({img})]({link})\n"
            md += f"**{text}**\n\n"

    return {
        "title": h1_title,
        "author": author,
        "date": date,
        "source_url": url,
        "featured_img": featured_img,
        "author_img": author_img,
        "markdown": md,
        "related": related_links,
        "filename_base": article_safe_filename(h1_title),
    }


def download_and_compress_image(url, session=None, max_px=900, quality=60, max_download_bytes=6*1024*1024):
    """يحمل صورة من رابط ويضغطها (resize + JPEG) ويرجعها كـ (b64, ext)
    عشان نضمّنها داخل ملف المقال (md/html) ويفضل شغال أوفلاين بدون
    اعتماد على إنترنت، بحجم أصغر بكتير من الصورة الأصلية.
    لو فشل التحميل أو الضغط بيرجع (None, None)."""
    if not HAS_ARTICLE_DEPS:
        return None, None
    try:
        sess = session or requests
        r = sess.get(url, headers=ARTICLE_HEADERS, timeout=12, stream=True)
        r.raise_for_status()
        chunks = []
        total_len = 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total_len += len(chunk)
            if total_len > max_download_bytes:
                return None, None
        raw = b"".join(chunks)
        if not raw:
            return None, None

        if HAS_PIL:
            try:
                img = PilImage.open(io.BytesIO(raw)).convert("RGB")
                img.thumbnail((max_px, max_px), PilImage.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
            except Exception:
                pass  # لو PIL فشل (GIF متحرك مثلاً) نرجع الصورة الخام تحت

        # بدون PIL أو فشل فتحها بـ PIL: نرجع البيانات الخام كما هي (بدون ضغط)
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "png" in ctype:
            ext = "png"
        elif "gif" in ctype:
            ext = "gif"
        elif "webp" in ctype:
            ext = "webp"
        else:
            ext = "jpeg"
        return base64.b64encode(raw).decode("utf-8"), ext
    except Exception:
        return None, None


def article_embed_images_offline(data, max_px=900, quality=60, progress_cb=None, max_workers=4):
    """يحمّل كل صور المقال (featured/author/body) ويضغطها ويستبدل
    روابطها داخل الـ markdown بصيغة data URI (base64) عشان المقال
    يفضل شغال أوفلاين بالكامل وبحجم أصغر.
    التحميل بيتم بالتوازي (عدة صور في نفس الوقت) عشان يكون أسرع
    من تحميلها واحدة تلو الأخرى، خصوصًا لو المقال فيه صور كتير.
    progress_cb(done, total) اختياري لتحديث واجهة المستخدم وقت التحميل."""
    if not HAS_ARTICLE_DEPS:
        return data

    md = data.get("markdown", "")
    urls = re.findall(r'!\[[^\]]*\]\((https?://[^)]+)\)', md)
    chart_urls = re.findall(r'\[\[chart:[^|]+\|(https?://[^\]]+)\]\]', md)
    urls = list(dict.fromkeys(urls + chart_urls))  # إزالة التكرار مع الحفاظ على الترتيب
    if not urls:
        return data

    from concurrent.futures import ThreadPoolExecutor, as_completed

    session = article_get_session()  # requests.Session آمنة للاستخدام من عدة threads
    total = len(urls)
    results = {}  # img_url -> (b64, ext)
    done_count = 0
    progress_lock = threading.Lock()

    def _fetch(img_url):
        return img_url, download_and_compress_image(img_url, session=session, max_px=max_px, quality=quality)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch, u) for u in urls]
        for future in as_completed(futures):
            try:
                img_url, (b64, ext) = future.result()
                results[img_url] = (b64, ext)
            except Exception:
                pass
            with progress_lock:
                done_count += 1
                d = done_count
            if progress_cb:
                try:
                    progress_cb(d, total)
                except Exception:
                    pass

    # الاستبدال بترتيب الظهور الأصلي في النص (مش بترتيب انتهاء التحميل)
    for img_url in urls:
        b64, ext = results.get(img_url, (None, None))
        if b64:
            data_uri = f"data:image/{ext};base64,{b64}"
            md = md.replace(f"({img_url})", f"({data_uri})")
            md = md.replace(f"|{img_url}]]", f"|{data_uri}]]")

    data = dict(data)
    data["markdown"] = md
    data["offline_images"] = True
    return data


def article_to_html(data):
    """يحول بيانات المقال إلى صفحة HTML مستقلة.
    الصور ممكن تكون روابط مباشرة أو data URI (base64) لو تم تفعيل
    الحفظ الأوفلاين عبر article_embed_images_offline."""
    title = _html.escape(data["title"])
    author = _html.escape(data["author"])
    date = _html.escape(data["date"])
    source = data["source_url"]

    URL_RE = re.compile(r'(https?://[^\s<]+)')
    MD_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
    CHART_RE = re.compile(r'^\[\[chart:(.+?)\|(.*?)\]\]$')

    chart_counter = 0

    body_lines = []
    md_lines = data["markdown"].split("\n")
    li = 0
    while li < len(md_lines):
        raw_line = md_lines[li]
        line = raw_line.strip()
        if not line:
            li += 1
            continue

        # جدول ماركداون: نجمع كل السطور المتتالية اللي تبدأ بـ "|" ونحوّلها لـ <table>
        if line.startswith("|") and line.endswith("|"):
            table_lines = []
            while li < len(md_lines) and md_lines[li].strip().startswith("|") and md_lines[li].strip().endswith("|"):
                table_lines.append(md_lines[li].strip())
                li += 1
            rows = [[c.strip() for c in tl.strip("|").split("|")] for tl in table_lines]
            # السطر الثاني هو فاصل الهيدر (--- --- ---) لو موجود
            if len(rows) >= 2 and all(re.fullmatch(r":?-+:?", c) for c in rows[1]):
                header, data_rows = rows[0], rows[2:]
            else:
                header, data_rows = rows[0], rows[1:]
            table_html = ['<table class="article-table">', "<tr>" + "".join(f"<th>{_html.escape(c)}</th>" for c in header) + "</tr>"]
            for row in data_rows:
                table_html.append("<tr>" + "".join(f"<td>{_html.escape(c)}</td>" for c in row) + "</tr>")
            table_html.append("</table>")
            body_lines.append("\n".join(table_html))
            continue

        li += 1
        if line.startswith("# "):
            continue  # العنوان موجود في الهيدر بالفعل
        if line.startswith("## "):
            body_lines.append(f"<h2>{_html.escape(line[3:])}</h2>")
            continue
        if line.startswith("Author:") or line.startswith("Date:") or line.startswith("Source:"):
            continue
        if line == "---":
            body_lines.append("<hr>")
            continue

        chart_match = CHART_RE.fullmatch(line)
        if chart_match:
            chart_counter += 1
            cid = f"chart_{chart_counter}"
            chart_src, fallback_uri = chart_match.group(1), chart_match.group(2)
            block = [f'<div class="chart-block" id="{cid}">']
            if fallback_uri:
                block.append(f'<img src="{_html.escape(fallback_uri)}" alt="Chart" class="chart-fallback">')
            else:
                block.append('<div class="chart-placeholder">📊 رسم بياني تفاعلي</div>')
            block.append(
                f'<button class="chart-toggle-btn" '
                f'onclick="loadChart(\'{cid}\', \'{_html.escape(chart_src)}\')">'
                f'▶️ تشغيل النسخة التفاعلية (يحتاج إنترنت)</button>'
            )
            block.append('</div>')
            body_lines.append("\n".join(block))
            continue

        full_img = MD_IMG_RE.fullmatch(line)
        if full_img:
            alt, src = full_img.group(1), full_img.group(2)
            body_lines.append(f'<img src="{_html.escape(src)}" alt="{_html.escape(alt)}">')
            continue

        # رابط صورة مصغّرة لمقال ذو صلة: [![thumb](img)](link)
        thumb_match = re.fullmatch(r'\[!\[thumb\]\(([^)]+)\)\]\(([^)]+)\)', line)
        if thumb_match:
            img_src, link_href = thumb_match.group(1), thumb_match.group(2)
            body_lines.append(f'<a href="{_html.escape(link_href)}"><img class="thumb" src="{_html.escape(img_src)}"></a>')
            continue

        is_bold_line = line.startswith("**") and line.endswith("**") and len(line) > 4
        is_italic_line = line.startswith("*") and line.endswith("*") and not is_bold_line and len(line) > 2
        text_for_links = line[2:-2] if is_bold_line else (line[1:-1] if is_italic_line else line)

        # أولاً: روابط Markdown [text](url) - نهرب النص الخارجي فقط، لا الروابط الناتجة
        def repl_link(m):
            return f'\x00LINK\x00{_html.escape(m.group(2))}\x00{_html.escape(m.group(1))}\x00ENDLINK\x00'
        placeholder_text = MD_LINK_RE.sub(repl_link, text_for_links)

        # نهرب أي نص متبقي (غير الروابط) قبل تحويل الروابط العادية المتبقية
        parts = re.split(r'(\x00LINK\x00.*?\x00ENDLINK\x00)', placeholder_text)
        out_parts = []
        for part in parts:
            link_match = re.fullmatch(r'\x00LINK\x00(.*?)\x00(.*?)\x00ENDLINK\x00', part)
            if link_match:
                href, text = link_match.group(1), link_match.group(2)
                out_parts.append(f'<a href="{href}" target="_blank">{text}</a>')
            else:
                escaped = _html.escape(part)
                escaped = URL_RE.sub(lambda m: f'<a href="{_html.escape(m.group(0))}" target="_blank">{_html.escape(m.group(0))}</a>', escaped)
                out_parts.append(escaped)
        line_html = "".join(out_parts)

        if is_bold_line:
            body_lines.append(f"<p><strong>{line_html}</strong></p>")
        elif is_italic_line:
            body_lines.append(f'<p><em class="caption">{line_html}</em></p>')
        else:
            body_lines.append(f"<p>{line_html}</p>")

    body_html = "\n".join(body_lines)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{
    font-family: sans-serif;
    max-width: 720px;
    margin: 0 auto;
    padding: 16px;
    background: #f5f6f7;
    color: #1c1e21;
    line-height: 1.7;
    direction: rtl;
  }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  .meta {{ color: #65676b; font-size: 13px; margin-bottom: 16px; }}
  .meta a {{ color: #1877f2; }}
  img {{ max-width: 100%; height: auto; border-radius: 6px; display: block; margin: 12px 0; }}
  img.thumb {{ max-width: 160px; }}
  p {{ margin: 10px 0; }}
  em.caption {{ display: block; color: #65676b; font-size: 13px; text-align: center; margin: -4px 0 14px; }}
  table.article-table {{ border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14px; background: #fff; }}
  table.article-table th, table.article-table td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: center; }}
  table.article-table th {{ background: #eef0f2; }}
  a {{ color: #1877f2; text-decoration: none; word-break: break-all; }}
  a:hover {{ text-decoration: underline; }}
  hr {{ border: none; border-top: 1px solid #ccd0d5; margin: 20px 0; }}
  h2 {{ font-size: 17px; color: #65676b; margin-top: 24px; }}
  .chart-block {{ margin: 16px 0; background: #fff; border-radius: 8px; padding: 10px; text-align: center; }}
  .chart-fallback {{ width: 100%; border-radius: 6px; margin: 0 0 8px; }}
  .chart-placeholder {{ padding: 30px; color: #65676b; background: #eef0f2; border-radius: 6px; margin-bottom: 8px; }}
  .chart-toggle-btn {{ display: inline-block; width: 100%; padding: 10px; border: none; border-radius: 6px;
                        background: #1877f2; color: #fff; font-size: 14px; cursor: pointer; }}
  .chart-toggle-btn:hover {{ background: #145dbf; }}
  .chart-block iframe {{ width: 100%; min-height: 420px; border: none; border-radius: 6px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">✍️ {author} &nbsp;|&nbsp; 📅 {date} &nbsp;|&nbsp; <a href="{_html.escape(source)}" target="_blank">Source</a></div>
{body_html}
<script>
function loadChart(chartId, src) {{
  var block = document.getElementById(chartId);
  if (!block) return;
  block.innerHTML = '<iframe src="' + src + '" loading="lazy" allowfullscreen></iframe>';
}}
</script>
</body>
</html>"""


# =========================
# ENGINE
# =========================
class Engine:
    def __init__(self):
        # كاش لآخر mtime لكل مجلد صور - بيتفحص فقط لو المجلد فعلاً تغيّر
        # من آخر مرة، عشان نتجنب os.listdir لمجلدات فيها آلاف الصور كل
        # ضغطة GRAB/ATTACH. مش بنصفّره في reset() عشان RESET (زرار البوست)
        # ميجبرش إعادة فحص كامل غير ضروري.
        self._folder_mtime_cache = {}
        self._folder_files_cache = {}
        self.reset()

    def reset(self):
        self.article_data  = None     # آخر نتيجة من grab_article() - لعرض الحالة فقط
        self.article_url   = ""
        self.post         = ""
        self.post_images  = []
        self.grabbed      = []
        self.last_clip    = ""
        self.pending      = ""
        self.post_time    = 0
        self.post_link    = ""
        self.quote_text   = ""   # نص البوست المُقتبَس (Shared Post)
        self.quote_link   = ""   # لينك البوست المُقتبَس
        self.quote_images = []   # صور البوست المُقتبَس
        self.quote_avatar_b64  = ""    # أفاتار صاحب البوست المُقتبَس
        self.quote_avatar_ext  = "png"
        self.quote_author_name = ""    # اسم صاحب البوست المُقتبَس
        self.comments     = []
        self.next_id      = 1
        self.history      = []
        self.saved        = False
        # current_node: آخر تعليق/رد تمت إضافته (نقطة المرجع لكل أزرار link)
        self.current_node = None
        # last_new: آخر تعليق من نوع "new" (الشخص الجديد اللي بدأ الثريد)
        self.last_new     = None
        # last_root: آخر تعليق من نوع root (new أو author) - مرجع زرار link first
        self.last_root    = None
        # avatar + اسم صاحب البوست (يتم اختيارهم من القائمة المنسدلة)
        self.author_name  = ""
        self.author_avatar_b64 = ""
        self.author_avatar_ext = "png"
        self.last_scan_error = ""

    def add_comment(self, text, role, parent=None, reply_to=None):
        """
        parent:   العنصر الذي يحتوي بصرياً (nesting) - بيتحدد بناءً على شكل العرض في الفيس
        reply_to: اسم/مرجع الشخص اللي ده رد عليه (للسهم/التلميح)
        """
        node = {
            "id":       self.next_id,
            "role":     role,
            "text":     text,
            "imgs":     [],
            "replies":  [],
            "parent":   parent,
            "reply_to": reply_to,
        }
        self.next_id += 1
        if parent is None:
            self.comments.append(node)
            self.last_root = node
        else:
            parent["replies"].append(node)

        self.current_node = node
        if role == "new":
            self.last_new = node
        return node

    def get_new_images(self):
        self.last_scan_error = ""
        folders = ["/sdcard/DCIM/Facebook", "/sdcard/Download", "/sdcard/DCIM/Camera",
                   "/sdcard/Pictures/Screenshots", "/sdcard/DCIM/Screenshots",
                   "/sdcard/Pictures"]
        imgs = []
        any_folder_found = False
        for fldr in folders:
            try:
                if not os.path.exists(fldr):
                    continue
                any_folder_found = True

                # mtime المجلد بيتغيّر فقط لو اتضاف/اتشال ملف منه (إنشاء/حذف)،
                # فلو ماتغيّرش من آخر فحص، نستخدم القائمة المخزّنة بدل ما نعمل
                # os.listdir تاني (مكلفة لو فيه آلاف الصور)
                folder_mtime = os.path.getmtime(fldr)
                cached_mtime = self._folder_mtime_cache.get(fldr)
                if cached_mtime is not None and cached_mtime == folder_mtime:
                    file_list = self._folder_files_cache.get(fldr, [])
                else:
                    file_list = os.listdir(fldr)
                    self._folder_mtime_cache[fldr] = folder_mtime
                    self._folder_files_cache[fldr] = file_list

                for f in file_list:
                    if f.lower().endswith((".jpg", ".png", ".jpeg", ".webp")):
                        path = os.path.join(fldr, f)
                        if path not in self.grabbed:
                            if self.post_time == 0 or os.path.getmtime(path) >= self.post_time:
                                imgs.append(path)
            except PermissionError as e:
                self.last_scan_error = "PermissionError: " + str(e)
            except Exception as e:
                self.last_scan_error = type(e).__name__ + ": " + str(e)

        if not any_folder_found and not self.last_scan_error:
            self.last_scan_error = "Image folders not found - check storage permission"

        return sorted(imgs, key=os.path.getmtime)


# =========================
# دوال ضغط الصور — على مستوى الـ module عشان يستخدمها do_save وأي مكان تاني
# =========================
_SAVE_MAX_PX  = 1080
_SAVE_QUALITY = 65
_AV_MAX       = 120
_AV_QUAL      = 70


def _strip_jpeg_exif(data):
    """يشيل الـ APP1/EXIF من JPEG بدون مكتبات خارجية — يوفر 100-500KB"""
    out = bytearray(b'\xff\xd8')
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xff:
            break
        marker = data[i + 1]
        if marker in (0xe1,):  # APP1 = EXIF
            length = int.from_bytes(data[i+2:i+4], 'big') + 2
            i += length
            continue
        if marker in (0xd9, 0xda):  # EOI, SOS
            out += data[i:]
            break
        if i + 4 <= len(data):
            length = int.from_bytes(data[i+2:i+4], 'big') + 2
            out += data[i:i+length]
            i += length
        else:
            out += data[i:]
            break
    return bytes(out)


def _kivy_compress(src_path, max_px, quality):
    """ضغط عبر Kivy CoreImage — يشتغل دايماً على أندرويد"""
    texture = CoreImage(src_path).texture
    w, h = texture.size
    scale = min(max_px / max(w, h, 1), 1.0)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if HAS_PIL:
        img = PilImage.open(src_path).convert("RGB")
        img.thumbnail((max_px, max_px), PilImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
    buf = io.BytesIO(texture.pixels)
    return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"


def compress_to_b64(src_path, max_px=_SAVE_MAX_PX, quality=_SAVE_QUALITY):
    try:
        if HAS_PIL:
            img = PilImage.open(src_path).convert("RGB")
            img.thumbnail((max_px, max_px), PilImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
        with open(src_path, "rb") as fp:
            data = fp.read()
        if len(data) > 300_000 and data[:2] == b'\xff\xd8':
            data = _strip_jpeg_exif(data)
        ext = os.path.splitext(src_path)[1].lower().lstrip(".") or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        return base64.b64encode(data).decode("utf-8"), ext
    except Exception:
        return None, None


def compress_to_b64_cached(src_path, cache, max_px=_SAVE_MAX_PX, quality=_SAVE_QUALITY):
    """زي compress_to_b64 بالظبط، لكن بيخزن النتيجة في cache (dict)
    عشان لو نفس الصورة اتطلبت تاني (مثلاً وقت حفظ HTML و Markdown مع بعض
    في وضع "Both")، نرجّع النتيجة المحسوبة قبل كده بدل ما نعيد فتح
    وضغط نفس الصورة من جديد.
    cache المتوقع يكون dict فاضي بيتعمله reset قبل كل عملية حفظ مستقلة."""
    if cache is not None and src_path in cache:
        return cache[src_path]
    result = compress_to_b64(src_path, max_px=max_px, quality=quality)
    if cache is not None:
        cache[src_path] = result
    return result


def compress_av_b64(b64_data, ext_str, av_max=_AV_MAX, av_qual=_AV_QUAL):
    try:
        if HAS_PIL:
            raw = base64.b64decode(b64_data)
            img = PilImage.open(io.BytesIO(raw)).convert("RGB")
            img.thumbnail((av_max, av_max), PilImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=av_qual, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
        return b64_data, ext_str
    except Exception:
        return b64_data, ext_str


engine = Engine()


def trim_name(name, max_len=16):
    return name[:13] + "..." if len(name) > max_len else name


# =========================
# AVATAR PICKER POPUP
# =========================
class AvatarPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = "Choose Avatar"
        self.size_hint = (0.9, 0.9)
        self.on_select = on_select

        self.root_layout = BoxLayout(orientation="vertical")

        self.scroll = ScrollView()
        self.grid_container = BoxLayout(orientation="vertical")
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=0.08)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout

        # تحميل أوتوماتيك عند الفتح
        self._refresh_grid()

    def _refresh_grid(self):
        global AVATARS
        fresh = load_avatars()
        AVATARS.clear()
        AVATARS.extend(fresh)

        self.grid_container.clear_widgets()
        if not AVATARS:
            self.grid_container.add_widget(
                Label(text="No avatars yet.\nUse ADD to add avatars.")
            )
            return

        from kivy.uix.floatlayout import FloatLayout

        grid = GridLayout(cols=5, size_hint_y=None, spacing=4, padding=4)
        grid.bind(minimum_height=grid.setter("height"))
        for idx, av in enumerate(AVATARS):
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=120)
            try:
                img_path = av.get("path", "")
                img_ext = (av.get("ext") or "png").lower()
                if img_path and os.path.exists(img_path):
                    if img_ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
                        raise ValueError("unsupported ext: " + img_ext)
                    core_img = CoreImage(img_path, ext=img_ext)
                else:
                    if img_ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
                        raise ValueError("unsupported ext: " + img_ext)
                    raw = base64.b64decode(av["b64"])
                    core_img = CoreImage(io.BytesIO(raw), ext=img_ext)
                img_widget = Image(texture=core_img.texture, size_hint=(1, 1))
            except Exception:
                img_widget = Label(text="?", size_hint=(1, 1))

            # نستخدم FloatLayout عشان نركب: الصورة + زرار الاختيار (فوقها)
            # + زرار "⋮" menu صغير في الزاوية العليا (Edit/Delete) بدل الزرار
            # الأحمر القديم اللي كان تحت الصورة.
            # ملاحظة: float_cell يملأ بالضبط نفس مساحة الصورة (لا أكبر ولا أصغر)،
            # والاسم تحته يملأ باقي ارتفاع الخلية بالكامل بدون أي فراغ ضايع.
            float_cell = FloatLayout(size_hint_y=None, height=88)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, i=idx: self._pick(i))

            menu_btn = Button(text="⋮", size_hint=(None, None), size=(28, 28),
                              pos_hint={"right": 1, "top": 1},
                              background_color=(0, 0, 0, 0.55), font_size="14sp")
            menu_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            float_cell.add_widget(menu_btn)
            cell.add_widget(float_cell)

            # label الاسم - يلتزم بعرض الخلية (نفس عرض الصورة) ولا يتجاوزه
            av_name = trim_name(av.get("name", "No Name"))
            lbl_name = Label(text=av_name, size_hint_y=None, height=32,
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            # زرار شفاف فوق الـ label للضغط
            cell_inner = BoxLayout(orientation="vertical", size_hint_y=None, height=32)
            from kivy.uix.floatlayout import FloatLayout as _FL
            name_float = _FL(size_hint_y=None, height=32)
            lbl_name.pos_hint = {"x": 0, "y": 0}
            name_sel_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                  background_color=(0, 0, 0, 0))
            name_sel_btn.bind(on_press=lambda x, i=idx: self._pick(i))
            name_float.add_widget(lbl_name)
            name_float.add_widget(name_sel_btn)
            cell.add_widget(name_float)

            grid.add_widget(cell)
        self.grid_container.add_widget(grid)

    def _pick(self, idx):
        self.on_select(AVATARS[idx])
        self.dismiss()

    def _open_item_menu(self, idx):
        """زرار ⋮ العلوي: يفتح قائمة صغيرة فيها Edit Avatar / Delete Avatar
        بدل الزرار الأحمر الثابت اللي كان تحت كل صورة."""
        av = AVATARS[idx]
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.3))

        edit_btn = Button(text="✎ Edit Avatar", background_color=(0.2, 0.55, 0.85, 1))
        del_btn  = Button(text="🗑 Delete Avatar", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(edit_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.7, 0.4))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _edit(self, idx):
        av = AVATARS[idx]

        def on_saved(new_name, new_b64, new_ext, new_path):
            AVATARS[idx]["name"] = new_name
            if new_path:
                AVATARS[idx]["path"] = new_path
                AVATARS[idx]["ext"] = new_ext
                AVATARS[idx]["b64"] = new_b64
            save_avatars()
            # لو نفس المسار موجود في SCROLL_AVATARS، حدّث الاسم هناك كمان
            for s in SCROLL_AVATARS:
                if s.get("path") == av.get("path"):
                    s["name"] = new_name
                    if new_path:
                        s["path"] = new_path
                        s["ext"] = new_ext
                        s["b64"] = new_b64
            save_scroll_avatars()
            self._refresh_grid()

        popup = EditAvatarPopup(av, on_saved=on_saved)
        popup.open()

    def _delete(self, idx):
        av = AVATARS[idx]
        def confirm_delete(instance):
            confirm_popup.dismiss()
            img_path = av.get("path", "")
            scroll_paths = {s.get("path", "") for s in SCROLL_AVATARS}
            if img_path and img_path not in scroll_paths and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except Exception:
                    pass
            AVATARS.pop(idx)
            save_avatars()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Delete "{av.get("name","")}"?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        no_btn  = Button(text="Cancel")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Delete", content=content,
                              size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=confirm_delete)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()


# =========================
# EditAvatarPopup: تعديل اسم الأفاتار و/أو صورته
# يُستخدم من AvatarPopup و ScrollAvatarPopup
# =========================
class EditAvatarPopup(Popup):
    def __init__(self, avatar, on_saved, on_saved_with_link=None, show_link=False, **kwargs):
        super().__init__(**kwargs)
        self.title = "Edit Scroll" if show_link else "Edit Avatar"
        self.size_hint = (0.85, 0.78) if show_link else (0.85, 0.7)
        self.avatar = avatar
        self.on_saved = on_saved
        self.on_saved_with_link = on_saved_with_link
        self.show_link = show_link
        self._new_b64 = None
        self._new_ext = None

        root = BoxLayout(orientation="vertical", spacing=8, padding=8)

        self.preview_box = BoxLayout(size_hint_y=0.36 if show_link else 0.4)
        self._render_preview()
        root.add_widget(self.preview_box)

        change_img_btn = Button(text="🖼 Change Image (from device)", size_hint_y=0.13)
        change_img_btn.bind(on_press=self._pick_new_image)
        root.add_widget(change_img_btn)

        self.name_input = TextInput(text=avatar.get("name", ""), multiline=False, size_hint_y=0.13)
        root.add_widget(self.name_input)

        if show_link:
            self.link_input = TextInput(text=avatar.get("link", ""), multiline=False, size_hint_y=0.13,
                                        hint_text="Link")
            root.add_widget(self.link_input)

        btn_row = BoxLayout(size_hint_y=0.13, spacing=6)
        save_btn = Button(text="Save", background_color=(0.2, 0.7, 0.3, 1))
        cancel_btn = Button(text="Cancel")
        save_btn.bind(on_press=self._save)
        cancel_btn.bind(on_press=lambda x: self.dismiss())
        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        self.content = root

    def _render_preview(self):
        self.preview_box.clear_widgets()
        try:
            if self._new_b64:
                raw = base64.b64decode(self._new_b64)
                core_img = CoreImage(io.BytesIO(raw), ext=self._new_ext)
            else:
                img_path = self.avatar.get("path", "")
                img_ext = (self.avatar.get("ext") or "png").lower()
                if img_path and os.path.exists(img_path):
                    core_img = CoreImage(img_path, ext=img_ext)
                else:
                    raw = base64.b64decode(self.avatar.get("b64", ""))
                    core_img = CoreImage(io.BytesIO(raw), ext=img_ext)
            self.preview_box.add_widget(Image(texture=core_img.texture))
        except Exception:
            self.preview_box.add_widget(Label(text="(preview unavailable)"))

    def _pick_new_image(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            return
        last_img = imgs[-1]
        engine.grabbed.append(last_img)
        ext = os.path.splitext(last_img)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            with open(last_img, "rb") as _f:
                self._new_b64 = base64.b64encode(_f.read()).decode("utf-8")
            self._new_ext = ext
        except Exception:
            return
        self._render_preview()

    def _save(self, x):
        name = self.name_input.text.strip()
        if not name:
            return
        new_path = ""
        new_ext = self.avatar.get("ext", "png")
        new_b64 = self.avatar.get("b64", "")
        if self._new_b64:
            try:
                new_path, new_ext = save_avatar_image(self._new_b64, self._new_ext, name)
                new_b64 = self._new_b64
            except Exception:
                new_path = ""
        if self.show_link:
            link = self.link_input.text.strip()
            self.on_saved_with_link(name, new_b64, new_ext, new_path, link)
        else:
            self.on_saved(name, new_b64, new_ext, new_path)
        self.dismiss()


# =========================
# NamePopup: يفتح بعد جلب صورة جديدة لكتابة اسم
# ويضيفها إلى AVATARS كعنصر جديد
# =========================
class NamePopup(Popup):
    """بعد اختيار صورة جديدة: المستخدم يكتب الاسم، وممكن يكتب لينك (اختياري).
    بدل زرار "Add" واحد، عندنا 3 أزرار وجهة:
      - Avatar: يحفظ الاسم + الصورة في AVATARS فقط (يتجاهل اللينك لو موجود)
      - Scroll: يحفظ الاسم + الصورة + اللينك في SCROLL_AVATARS فقط
                (بيتطلب لينك، لأن الضغط على صورة Scroll بيفتح اللينك)
      - Both:   يحفظ في الاتنين مع بعض (نفس الاسم/الصورة، واللينك في نسخة Scroll)
    on_confirm(name, b64_data, link, destination) حيث destination
    تكون "avatar" أو "scroll" أو "both".
    """
    def __init__(self, b64_data, ext, on_confirm, **kwargs):
        super().__init__(**kwargs)
        self.title = "Enter Avatar Name"
        self.size_hint = (0.85, 0.78)
        self.b64_data = b64_data
        self.on_confirm = on_confirm

        root = BoxLayout(orientation="vertical", spacing=8, padding=8)

        try:
            raw = base64.b64decode(b64_data)
            core_img = CoreImage(io.BytesIO(raw), ext=ext)
            img_widget = Image(texture=core_img.texture, size_hint_y=0.45)
            root.add_widget(img_widget)
        except Exception:
            root.add_widget(Label(text="(preview unavailable)", size_hint_y=0.45))

        self.name_input = TextInput(hint_text="Post author name", multiline=False, size_hint_y=0.12)
        root.add_widget(self.name_input)

        self.link_input = TextInput(hint_text="Link (required for Scroll / Both)", multiline=False, size_hint_y=0.12)
        root.add_widget(self.link_input)

        hint_lbl = Label(
            text="Choose destination:  Avatar = name+photo only  |  Scroll = name+photo+link  |  Both = both",
            size_hint_y=0.12, font_size="11sp", halign="center", valign="middle"
        )
        hint_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0] - 8, None)))
        root.add_widget(hint_lbl)

        btn_row = BoxLayout(size_hint_y=0.16, spacing=6)
        self.btn_avatar = Button(text="Avatar", background_color=(0.2, 0.55, 0.85, 1))
        self.btn_scroll = Button(text="Scroll", background_color=(0.1, 0.7, 0.4, 1))
        self.btn_both   = Button(text="Both",   background_color=(0.6, 0.4, 0.85, 1))
        self.btn_avatar.bind(on_press=lambda x: self._confirm("avatar"))
        self.btn_scroll.bind(on_press=lambda x: self._confirm("scroll"))
        self.btn_both.bind(on_press=lambda x: self._confirm("both"))
        btn_row.add_widget(self.btn_avatar)
        btn_row.add_widget(self.btn_scroll)
        btn_row.add_widget(self.btn_both)
        root.add_widget(btn_row)

        cancel_btn = Button(text="Cancel", size_hint_y=0.1)
        cancel_btn.bind(on_press=lambda x: self.dismiss())
        root.add_widget(cancel_btn)

        self.content = root

    def _confirm(self, destination):
        name = self.name_input.text.strip()
        if not name:
            self.name_input.hint_text = "⚠ Name is required"
            return
        link = self.link_input.text.strip()
        if destination in ("scroll", "both") and not link:
            self.link_input.hint_text = "⚠ Link required for Scroll/Both"
            return
        self.on_confirm(name, self.b64_data, link, destination)
        self.dismiss()



# =========================
# SCROLL AVATAR POPUP
# قائمة الأفاتارات التي تحتوي على لينكات — الضغط على الصورة يفتح اللينك
# =========================
class ScrollAvatarPopup(Popup):
    def __init__(self, grab_avatar_cb=None, **kwargs):
        super().__init__(**kwargs)
        self.title = "Scroll — Tap image to open link"
        self.size_hint = (0.9, 0.9)
        self.grab_avatar_cb = grab_avatar_cb  # callback من UI لإضافة أفاتار جديد

        self.root_layout = BoxLayout(orientation="vertical")

        self.scroll = ScrollView()
        self.grid_container = BoxLayout(orientation="vertical")
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        self._refresh_grid()

    def _refresh_grid(self):
        global SCROLL_AVATARS
        fresh = load_scroll_avatars()
        SCROLL_AVATARS.clear()
        SCROLL_AVATARS.extend(fresh)

        self.grid_container.clear_widgets()
        if not SCROLL_AVATARS:
            self.grid_container.add_widget(
                Label(text="No linked avatars yet.")
            )
            return

        from kivy.uix.floatlayout import FloatLayout

        grid = GridLayout(cols=5, size_hint_y=None, spacing=4, padding=4)
        grid.bind(minimum_height=grid.setter("height"))

        for idx, av in enumerate(SCROLL_AVATARS):
            link = av.get("link", "")
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=120)

            # صورة الأفاتار — الضغط عليها يفتح اللينك
            try:
                img_path = av.get("path", "")
                img_ext = (av.get("ext") or "png").lower()
                if img_ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
                    raise ValueError("unsupported ext: " + img_ext)
                if img_path and os.path.exists(img_path):
                    core_img = CoreImage(img_path, ext=img_ext)
                else:
                    raw = base64.b64decode(av["b64"])
                    core_img = CoreImage(io.BytesIO(raw), ext=img_ext)
                img_widget = Image(texture=core_img.texture, size_hint=(1, 1))
            except Exception:
                img_widget = Label(text="?", size_hint=(1, 1))

            # float_cell يملأ بالضبط نفس مساحة الصورة، والاسم يملأ باقي الخلية كاملاً
            float_cell = FloatLayout(size_hint_y=None, height=88)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, lnk=link: self._open_link(lnk))

            menu_btn = Button(text="⋮", size_hint=(None, None), size=(28, 28),
                              pos_hint={"right": 1, "top": 1},
                              background_color=(0, 0, 0, 0.55), font_size="14sp")
            menu_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            float_cell.add_widget(menu_btn)
            cell.add_widget(float_cell)

            # اسم الأفاتار - يلتزم بعرض الخلية ولا يتجاوزها
            av_name = trim_name(av.get("name", "No Name"))
            lbl_name = Label(text=av_name, size_hint_y=None, height=32,
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            cell.add_widget(lbl_name)

            grid.add_widget(cell)

        self.grid_container.add_widget(grid)

    def _open_link(self, link):
        if not link:
            return
        # على أندرويد: نجرب Intent الأول لأنه الطريقة الموثوقة فعليًا.
        # webbrowser.open() ممكن "ينجح" ظاهريًا (مايرميش exception) من غير
        # ما يفتح حاجة فعلاً، فمكانه التجربة الأولى كان بيخلي الـ fallback
        # الصحيح (Intent) ميتفعّلش خالص حتى لو الرابط فشل يفتح.
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(link))
            PythonActivity.mActivity.startActivity(intent)
            return
        except Exception:
            pass
        # مش على أندرويد (تجربة على كمبيوتر) أو jnius غير متاح: نستخدم webbrowser
        try:
            import webbrowser
            webbrowser.open(link)
        except Exception:
            pass

    def _open_item_menu(self, idx):
        """زرار ⋮ العلوي: Edit Scroll / Delete Scroll بدل زرار Remove الثابت."""
        av = SCROLL_AVATARS[idx]
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.3))

        edit_btn = Button(text="✎ Edit Scroll", background_color=(0.2, 0.55, 0.85, 1))
        del_btn  = Button(text="🗑 Delete Scroll", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(edit_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.7, 0.4))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _edit(self, idx):
        av = SCROLL_AVATARS[idx]

        def on_saved(new_name, new_b64, new_ext, new_path, new_link):
            SCROLL_AVATARS[idx]["name"] = new_name
            SCROLL_AVATARS[idx]["link"] = new_link
            if new_path:
                SCROLL_AVATARS[idx]["path"] = new_path
                SCROLL_AVATARS[idx]["ext"] = new_ext
                SCROLL_AVATARS[idx]["b64"] = new_b64
            save_scroll_avatars()
            self._refresh_grid()

        popup = EditAvatarPopup(av, on_saved=None, on_saved_with_link=on_saved, show_link=True)
        popup.open()

    def _delete(self, idx):
        av = SCROLL_AVATARS[idx]
        def confirm_delete(instance):
            confirm_popup.dismiss()
            SCROLL_AVATARS.pop(idx)
            save_scroll_avatars()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Remove "{av.get("name","")}" from Scroll?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        no_btn  = Button(text="Cancel")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Delete", content=content,
                              size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=confirm_delete)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()


# =========================
# IMAGE FILE PICKER POPUP (وصول يدوي بالكامل - لاختيار صورة من أي مكان)
# =========================
class ImagePickerPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = "Browse and select an image"
        self.size_hint = (0.95, 0.95)
        self.on_select = on_select

        root = BoxLayout(orientation="vertical", spacing=6, padding=8)

        default_path = "/storage/emulated/0"
        if not os.path.exists(default_path):
            default_path = "/sdcard"

        self.file_chooser = FileChooserListView(
            path=default_path,
            filters=["*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG", "*.webp", "*.WEBP"],
            dirselect=False
        )
        root.add_widget(self.file_chooser)

        btn_row = BoxLayout(size_hint_y=None, height=50, spacing=10)

        select_btn = Button(text="✅ Select Image", background_color=(0.2, 0.6, 0.2, 1))
        select_btn.bind(on_press=self._validate_and_pick)

        cancel_btn = Button(text="Cancel")
        cancel_btn.bind(on_press=lambda x: self.dismiss())

        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        self.content = root

    def _validate_and_pick(self, instance):
        selected = self.file_chooser.selection
        if selected:
            self.dismiss()
            self.on_select(selected[0])


# =========================
# ZIP FILE PICKER POPUP (وصول يدوي بالكامل)
# =========================
class ZipPickerPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = "Browse and select a ZIP file"
        self.size_hint = (0.95, 0.95)
        self.on_select = on_select

        root = BoxLayout(orientation="vertical", spacing=6, padding=8)

        # تحديد المسار الافتراضي الحقيقي لذاكرة الهاتف عند فتح المستعرض
        default_path = "/storage/emulated/0"
        if not os.path.exists(default_path):
            default_path = "/sdcard"

        # إنشاء مستعرض الملفات اليدوي
        self.file_chooser = FileChooserListView(
            path=default_path,
            filters=["*.zip", "*.ZIP"],  # إظهار ملفات الـ ZIP فقط
            dirselect=False
        )
        root.add_widget(self.file_chooser)

        # أزرار التحكم السفلية
        btn_row = BoxLayout(size_hint_y=None, height=50, spacing=10)

        select_btn = Button(text="✅ Select File", background_color=(0.2, 0.6, 0.2, 1))
        select_btn.bind(on_press=self._validate_and_pick)

        cancel_btn = Button(text="Cancel")
        cancel_btn.bind(on_press=lambda x: self.dismiss())

        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        self.content = root

    def _validate_and_pick(self, instance):
        # جلب الملف الذي قمت بالضغط عليه وتحديده يدوياً
        selected = self.file_chooser.selection
        if selected:
            self.dismiss()
            self.on_select(selected[0])  # تمرير مسار الملف المختار للدالة الأساسية


# =========================
# ARTICLE POPUP
# رابط -> GRAB -> SAVE (يسأل MD أو HTML عند الحفظ)
# =========================
class ArticlePopup(Popup):
    def __init__(self, on_saved, **kwargs):
        super().__init__(**kwargs)
        self.title = "📰 Article Grabber"
        self.size_hint = (0.92, 0.88)
        self.on_saved = on_saved
        self.result = None   # نتيجة grab_article() الحالية
        self.busy = False

        root = BoxLayout(orientation="vertical", spacing=8, padding=10)

        root.add_widget(Label(text="Article URL:", size_hint_y=0.08, font_size="13sp"))

        self.url_input = TextInput(hint_text="https://example.com/article", multiline=False,
                                    size_hint_y=0.1, font_size="13sp")
        root.add_widget(self.url_input)

        btn_row = BoxLayout(size_hint_y=0.12, spacing=6)
        paste_btn = Button(text="Paste")
        paste_btn.bind(on_press=self._paste)
        self.grab_btn = Button(text="GRAB", background_color=(0.85, 0.5, 0.1, 1))
        self.grab_btn.bind(on_press=self._do_grab)
        reset_btn = Button(text="Reset", background_color=(0.6, 0.2, 0.2, 1))
        reset_btn.bind(on_press=self._do_reset)
        btn_row.add_widget(paste_btn)
        btn_row.add_widget(self.grab_btn)
        btn_row.add_widget(reset_btn)
        root.add_widget(btn_row)

        self.scroll = ScrollView(size_hint_y=0.5)
        self.preview = Label(text="(No article loaded yet)", halign="left", valign="top",
                              font_size="12sp", size_hint_y=None, markup=False)
        self.preview.bind(size=self._update_preview_text_size)
        self.scroll.add_widget(self.preview)
        root.add_widget(self.scroll)

        bottom_row = BoxLayout(size_hint_y=0.12, spacing=6)
        self.save_btn = Button(text="SAVE", background_color=(0.2, 0.6, 0.2, 1))
        self.save_btn.bind(on_press=self._do_save)
        close_btn = Button(text="Close")
        close_btn.bind(on_press=lambda x: self.dismiss())
        bottom_row.add_widget(self.save_btn)
        bottom_row.add_widget(close_btn)
        root.add_widget(bottom_row)

        self.content = root

    def _update_preview_text_size(self, instance, value):
        instance.text_size = (instance.width, None)
        instance.height = instance.texture_size[1]

    def _paste(self, x):
        try:
            clip = Clipboard.paste().strip()
            if clip:
                # ننظف فورًا أي سطور جديدة/مسافات جوه الرابط الملصوق
                # (TextInput single-line بيقدر يستوعب النص لكن لازم يكون نظيف
                # قبل ما نستخدمه في الطلب الفعلي)
                self.url_input.text = article_clean_url(clip)
        except Exception:
            pass

    def _do_reset(self, x):
        """مسح الرابط والمعاينة لبدء مقال جديد"""
        self.url_input.text = ""
        self.result = None
        engine.article_data = None
        engine.article_url = ""
        self.preview.markup = False
        self.preview.text = "(No article loaded yet)"

    def _do_grab(self, x):
        if self.busy:
            return
        url = article_clean_url(self.url_input.text.strip())
        if not url:
            self.preview.text = "⚠️ Enter article URL first."
            return
        if not HAS_ARTICLE_DEPS:
            self.preview.text = ("❌ requests / beautifulsoup4 libraries not installed in this build.\n"
                                  "Add them to requirements in buildozer.spec:\n"
                                  "requests,beautifulsoup4,certifi,urllib3,charset-normalizer,idna")
            return

        self.busy = True
        self.grab_btn.text = "Fetching..."
        self.grab_btn.disabled = True
        self.preview.text = "⏳ Fetching article..."

        def worker():
            res = grab_article(url)
            Clock.schedule_once(lambda dt: self._on_grabbed(res, url), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _on_grabbed(self, res, url):
        self.busy = False
        self.grab_btn.text = "GRAB"
        self.grab_btn.disabled = False

        if "error" in res:
            self.result = None
            self.preview.text = "❌ " + res["error"]
            return

        self.result = res
        engine.article_data = res
        engine.article_url = url

        preview_md = re.sub(r'\[\[chart:(.+?)\|.*?\]\]', r'📊 Interactive chart: \1', res['markdown'])
        preview_text = (
            f"[b]{res['title']}[/b]\n"
            f"✍️ {res['author']}   📅 {res['date']}\n"
            f"🔗 {res['source_url']}\n"
            f"{'—'*20}\n"
            f"{preview_md[:600]}..."
        )
        self.preview.markup = True
        self.preview.text = preview_text

    def _do_save(self, x):
        if not self.result:
            self.preview.text = "⚠️ Fetch an article first (press GRAB)."
            return

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="Choose save format:", font_size="14sp"))
        btn_row = BoxLayout(size_hint_y=None, height=46, spacing=8)
        md_btn = Button(text="📄 Markdown (.md)")
        html_btn = Button(text="🌐 HTML (.html)")
        btn_row.add_widget(md_btn)
        btn_row.add_widget(html_btn)
        content.add_widget(btn_row)
        cancel_btn = Button(text="Cancel", size_hint_y=None, height=40)
        content.add_widget(cancel_btn)

        choice_popup = Popup(title="Save Article", content=content, size_hint=(0.8, 0.32))
        md_btn.bind(on_press=lambda i: self._save_as(choice_popup, "md"))
        html_btn.bind(on_press=lambda i: self._save_as(choice_popup, "html"))
        cancel_btn.bind(on_press=lambda i: choice_popup.dismiss())
        choice_popup.open()

    def _save_as(self, choice_popup, fmt):
        choice_popup.dismiss()
        res = self.result
        if not res:
            return

        self.preview.markup = False
        self.preview.text = "⏳ Downloading and compressing images (offline)...\n0%"
        self.grab_btn.disabled = True

        def progress_cb(done, total):
            pct = int(done * 100 / total) if total else 100
            Clock.schedule_once(
                lambda dt: setattr(self.preview, "text",
                                    f"⏳ Downloading images (offline)...\n{done}/{total} ({pct}%)"),
                0
            )

        def worker():
            try:
                # ضغط أقوى: max_px=720، quality=45 للحصول على أقل حجم ممكن
                offline_res = article_embed_images_offline(res, max_px=720, quality=45, progress_cb=progress_cb)
            except Exception as e:
                offline_res = res
                Clock.schedule_once(lambda dt: setattr(self.preview, "text",
                                     "⚠️ Some images failed to download, saving without full offline: " + str(e)), 0)
            Clock.schedule_once(lambda dt: self._finish_save(offline_res, fmt), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_save(self, res, fmt):
        self.grab_btn.disabled = False

        save_dir = "/sdcard/Download"
        if not os.path.isdir(save_dir) or not os.access(save_dir, os.W_OK):
            save_dir = os.path.join(os.path.expanduser("~"), "Download")
            os.makedirs(save_dir, exist_ok=True)

        base_name = res["filename_base"]
        ext = "md" if fmt == "md" else "html"
        path = os.path.join(save_dir, f"{base_name}.{ext}")
        counter = 1
        while os.path.exists(path):
            path = os.path.join(save_dir, f"{base_name}_{counter}.{ext}")
            counter += 1

        try:
            if fmt == "md":
                out_text = re.sub(
                    r'\[\[chart:(.+?)\|(.*?)\]\]',
                    lambda m: (f"![chart]({m.group(2)})\n\n" if m.group(2) else "")
                              + f"📊 Interactive chart: {m.group(1)}",
                    res["markdown"]
                )
            else:
                html_out = article_to_html(res)
                # ضغط بسيط: إزالة السطور الفارغة المتكررة والمسافات الزائدة
                html_out = re.sub(r'\n\s*\n\s*\n', '\n\n', html_out)
                html_out = re.sub(r'[ \t]+\n', '\n', html_out)
                out_text = html_out
            with open(path, "w", encoding="utf-8") as f:
                f.write(out_text)
        except Exception as e:
            self.preview.text = "❌ Save failed: " + str(e)
            return

        self.preview.markup = False
        self.preview.text = "✓ Saved to:\n" + path
        if self.on_saved:
            self.on_saved(path)


# =========================
# TASK POPUP
# =========================
class TaskPopup(Popup):
    """نافذة قائمة المهمات: عرض المهمات الموجودة + زرار Create Task.
    الضغط على Create Task يفتح حقل اسم، وبعد التأكيد تتفتح نافذة
    تفاصيل المهمة (TaskDetailPopup) فورًا. الضغط على مهمة موجودة في
    القائمة يفتحها هي كمان."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "📋 Tasks"
        self.size_hint = (0.92, 0.88)

        self.root_layout = BoxLayout(orientation="vertical", spacing=6, padding=8)

        create_btn = Button(text="✚ Create Task", size_hint_y=None, height=44,
                            background_color=(0.2, 0.6, 0.3, 1))
        create_btn.bind(on_press=self._show_create_dialog)
        self.root_layout.add_widget(create_btn)

        self.scroll = ScrollView()
        self.tasks_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=4)
        self.tasks_container.bind(minimum_height=self.tasks_container.setter("height"))
        self.scroll.add_widget(self.tasks_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        self._refresh()

    def _refresh(self):
        global TASKS
        TASKS.clear()
        TASKS.extend(load_tasks())
        # توافق مع المهمات القديمة (كانت {"name","done"} بدون "items")
        for t in TASKS:
            if "items" not in t:
                t["items"] = []
        self.tasks_container.clear_widgets()

        if not TASKS:
            self.tasks_container.add_widget(
                Label(text="No tasks yet.\nPress '✚ Create Task' to create one.",
                      size_hint_y=None, height=60, halign="center"))
            return

        for idx, task in enumerate(TASKS):
            row = BoxLayout(size_hint_y=None, height=50, spacing=6)

            open_btn = Button(text=task.get("name", ""), halign="left", valign="middle",
                              font_size="13sp")
            open_btn.bind(on_press=lambda x, i=idx: self._open_task(i))

            count_lbl = Label(text=str(len(task.get("items", []))), size_hint_x=None,
                              width=34, font_size="12sp", color=(0.7, 0.7, 0.7, 1))

            del_btn = Button(text="🗑", size_hint_x=None, width=40,
                             background_color=(0.7, 0.2, 0.2, 1))
            del_btn.bind(on_press=lambda x, i=idx: self._delete_task(i))

            row.add_widget(open_btn)
            row.add_widget(count_lbl)
            row.add_widget(del_btn)
            self.tasks_container.add_widget(row)

    def _show_create_dialog(self, x):
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="Task name:", size_hint_y=0.3))
        name_input = TextInput(hint_text="Enter task name...", multiline=False, size_hint_y=0.35)
        content.add_widget(name_input)

        btn_row = BoxLayout(size_hint_y=0.3, spacing=8)
        ok_btn  = Button(text="Create", background_color=(0.2, 0.65, 0.3, 1))
        can_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(can_btn)
        content.add_widget(btn_row)

        dlg = Popup(title="Create Task", content=content, size_hint=(0.8, 0.36))

        def _create(inst):
            name = name_input.text.strip()
            if not name:
                name_input.hint_text = "⚠ Name required"
                return
            TASKS.append({"name": name, "items": []})
            save_tasks(TASKS)
            new_idx = len(TASKS) - 1
            dlg.dismiss()
            self._refresh()
            self._open_task(new_idx)

        ok_btn.bind(on_press=_create)
        can_btn.bind(on_press=lambda i: dlg.dismiss())
        dlg.open()

    def _open_task(self, idx):
        detail = TaskDetailPopup(idx, on_change=self._refresh)
        detail.open()

    def _delete_task(self, idx):
        TASKS.pop(idx)
        save_tasks(TASKS)
        self._refresh()


class TaskDetailPopup(Popup):
    """نافذة تفاصيل مهمة واحدة: شبكة أفاتارات (اسم + صورة + لينك).
    - الضغط على الصورة: يفتح لينك المصمم.
    - الضغط على الاسم: قائمة (Edit / Delete / Notes / Reset Counter).
    - عداد فوق كل عنصر: الضغط عليه يزيد ١، ٢، ٣... ويُصفّر من قائمة الاسم."""
    def __init__(self, task_idx, on_change=None, **kwargs):
        super().__init__(**kwargs)
        self.task_idx = task_idx
        self.on_change = on_change
        task = TASKS[self.task_idx]
        self.title = f"📋 {task.get('name','Task')}"
        self.size_hint = (0.94, 0.9)

        self.root_layout = BoxLayout(orientation="vertical")

        top_row = BoxLayout(size_hint_y=None, height=46, spacing=6, padding=(4, 2))
        add_btn = Button(text="➕ Add Avatar", font_size="12sp",
                         background_color=(0.15, 0.6, 0.35, 1))
        add_btn.bind(on_press=self._do_add_item)
        top_row.add_widget(add_btn)
        self.root_layout.add_widget(top_row)

        self.scroll = ScrollView()
        self.grid_container = BoxLayout(orientation="vertical")
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        self._refresh_grid()

    def _task(self):
        return TASKS[self.task_idx]

    def _items(self):
        return self._task().setdefault("items", [])

    def _persist(self):
        save_tasks(TASKS)
        if self.on_change:
            self.on_change()

    def _refresh_grid(self):
        from kivy.uix.floatlayout import FloatLayout

        self.grid_container.clear_widgets()
        items = self._items()
        if not items:
            self.grid_container.add_widget(
                Label(text="No avatars in this task yet.\nPress '➕ Add Avatar' to add one.")
            )
            return

        grid = GridLayout(cols=4, size_hint_y=None, spacing=4, padding=4)
        grid.bind(minimum_height=grid.setter("height"))

        for idx, av in enumerate(items):
            link = av.get("link", "")
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=180)

            try:
                img_path = av.get("path", "")
                img_ext = (av.get("ext") or "png").lower()
                if img_ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
                    raise ValueError("unsupported ext: " + img_ext)
                if img_path and os.path.exists(img_path):
                    core_img = CoreImage(img_path, ext=img_ext)
                else:
                    raw = base64.b64decode(av["b64"])
                    core_img = CoreImage(io.BytesIO(raw), ext=img_ext)
                img_widget = Image(texture=core_img.texture, size_hint=(1, 1))
            except Exception:
                img_widget = Label(text="?", size_hint=(1, 1))

            float_cell = FloatLayout(size_hint_y=None, height=130)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, lnk=link: self._open_link(lnk))

            timer_val = av.get("timer", "")

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            cell.add_widget(float_cell)

            av_name = trim_name(av.get("name", "No Name"))
            name_btn = Button(text=av_name, size_hint_y=None, height=36,
                              font_size="10sp", background_color=(0.18, 0.18, 0.2, 1))
            name_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))
            cell.add_widget(name_btn)

            if timer_val:
                # اقتطاع النص لو طال مع إضافة نقاط في النهاية
                max_chars = 14
                display_timer = timer_val if len(timer_val) <= max_chars else timer_val[:max_chars - 1] + "…"
                timer_row = Label(text=f"• {display_timer}",
                                  size_hint_y=None, height=22,
                                  font_size="9sp", color=(1, 0.85, 0.3, 1),
                                  bold=True, halign="center", valign="middle")
                timer_row.bind(size=timer_row.setter("text_size"))
                cell.add_widget(timer_row)
                # نزود ارتفاع الخلية عشان السطر الجديد ما يتقطعش
                cell.height = 202

            grid.add_widget(cell)

        self.grid_container.add_widget(grid)

    def _do_add_item(self, x):
        """يفتح متصفح ملفات يدوي لاختيار صورة من أي مكان، ثم اسم + لينك ويضيفها لعناصر المهمة."""
        picker = ImagePickerPopup(on_select=self._on_image_picked)
        picker.open()

    def _on_image_picked(self, img_path):
        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            with open(img_path, "rb") as _f:
                b64_data = base64.b64encode(_f.read()).decode("utf-8")
        except Exception:
            return

        root = BoxLayout(orientation="vertical", spacing=8, padding=10)

        try:
            raw = base64.b64decode(b64_data)
            core_img = CoreImage(io.BytesIO(raw), ext=ext)
            img_widget = Image(texture=core_img.texture, size_hint_y=0.45)
            root.add_widget(img_widget)
        except Exception:
            root.add_widget(Label(text="(preview unavailable)", size_hint_y=0.45))

        name_input = TextInput(hint_text="Name", multiline=False, size_hint_y=0.12)
        link_input = TextInput(hint_text="Link (required)", multiline=False, size_hint_y=0.12)
        root.add_widget(name_input)
        root.add_widget(link_input)

        btn_row = BoxLayout(size_hint_y=0.16, spacing=6)
        ok_btn  = Button(text="✓ Add", background_color=(0.15, 0.6, 0.35, 1))
        can_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(can_btn)
        root.add_widget(btn_row)

        add_popup = Popup(title="Add Avatar", content=root, size_hint=(0.82, 0.7))
        captured_ext = ext

        def _confirm(inst):
            name = name_input.text.strip()
            link = link_input.text.strip()
            if not name:
                name_input.hint_text = "⚠ Name required"
                return
            if not link:
                link_input.hint_text = "⚠ Link required"
                return
            try:
                img_path, saved_ext = save_avatar_image(b64_data, captured_ext, name)
            except Exception:
                img_path, saved_ext = "", captured_ext
            entry = {"name": name, "link": link, "path": img_path,
                     "ext": saved_ext, "b64": b64_data, "notes": "", "count": 0}
            self._items().append(entry)
            self._persist()
            add_popup.dismiss()
            self._refresh_grid()

        ok_btn.bind(on_press=_confirm)
        can_btn.bind(on_press=lambda i: add_popup.dismiss())
        add_popup.open()

    def _open_link(self, link):
        if not link:
            return
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(link))
            PythonActivity.mActivity.startActivity(intent)
            return
        except Exception:
            pass
        try:
            import webbrowser
            webbrowser.open(link)
        except Exception:
            pass

    def _increment_counter(self, idx):
        items = self._items()
        items[idx]["count"] = items[idx].get("count", 0) + 1
        self._persist()
        self._refresh_grid()

    def _open_item_menu(self, idx):
        av = self._items()[idx]
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.22))

        edit_btn   = Button(text="✎ Edit", background_color=(0.2, 0.55, 0.85, 1))
        notes_btn  = Button(text="📝 Notes", background_color=(0.55, 0.5, 0.15, 1))
        timer_btn  = Button(text="⏱ Edit Timer", background_color=(0.3, 0.45, 0.6, 1))
        del_btn    = Button(text="🗑 Delete", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(edit_btn)
        content.add_widget(notes_btn)
        content.add_widget(timer_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.7, 0.55))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        notes_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit_notes(idx)))
        timer_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit_timer(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _edit(self, idx):
        av = self._items()[idx]

        def on_saved(new_name, new_b64, new_ext, new_path, new_link):
            items = self._items()
            items[idx]["name"] = new_name
            items[idx]["link"] = new_link
            if new_path:
                items[idx]["path"] = new_path
                items[idx]["ext"] = new_ext
                items[idx]["b64"] = new_b64
            self._persist()
            self._refresh_grid()

        popup = EditAvatarPopup(av, on_saved=None, on_saved_with_link=on_saved, show_link=True)
        popup.open()

    def _edit_notes(self, idx):
        av = self._items()[idx]
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        notes_input = TextInput(text=av.get("notes", ""), hint_text="Write notes / details...",
                                multiline=True)
        content.add_widget(notes_input)

        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        save_btn = Button(text="Save", background_color=(0.2, 0.65, 0.3, 1))
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        notes_popup = Popup(title="Notes", content=content, size_hint=(0.85, 0.6))

        def _save(inst):
            self._items()[idx]["notes"] = notes_input.text
            self._persist()
            notes_popup.dismiss()

        save_btn.bind(on_press=_save)
        cancel_btn.bind(on_press=lambda x: notes_popup.dismiss())
        notes_popup.open()

    def _edit_timer(self, idx):
        av = self._items()[idx]
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        content.add_widget(Label(text="Timer / label (e.g. 5  or  s1 ep 4)",
                                 size_hint_y=None, height=36, font_size="12sp"))
        timer_input = TextInput(text=av.get("timer", ""), hint_text="e.g. 5  or  s1 ep 4",
                                multiline=False)
        content.add_widget(timer_input)

        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        save_btn   = Button(text="Save", background_color=(0.2, 0.65, 0.3, 1))
        clear_btn  = Button(text="Clear", background_color=(0.5, 0.3, 0.1, 1))
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(save_btn)
        btn_row.add_widget(clear_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        timer_popup = Popup(title="Edit Timer", content=content, size_hint=(0.82, 0.38))

        def _save(inst):
            self._items()[idx]["timer"] = timer_input.text.strip()
            self._persist()
            timer_popup.dismiss()
            self._refresh_grid()

        def _clear(inst):
            self._items()[idx]["timer"] = ""
            self._persist()
            timer_popup.dismiss()
            self._refresh_grid()

        save_btn.bind(on_press=_save)
        clear_btn.bind(on_press=_clear)
        cancel_btn.bind(on_press=lambda x: timer_popup.dismiss())
        timer_popup.open()

    def _delete(self, idx):
        av = self._items()[idx]

        def confirm_delete(instance):
            confirm_popup.dismiss()
            self._items().pop(idx)
            self._persist()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Remove "{av.get("name","")}" from this task?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        no_btn  = Button(text="Cancel")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Delete", content=content, size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=confirm_delete)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()


# =========================
# UI
# =========================
class UI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=10, spacing=5)

        row1 = BoxLayout(size_hint_y=0.15)
        row1.add_widget(Button(text="RESET",  on_press=self.do_reset))
        row1.add_widget(Button(text="UNDO",   on_press=self.do_undo))
        row1.add_widget(Button(text="GRAB",   on_press=self.do_grab))
        row1.add_widget(Button(text="ATTACH", on_press=self.do_attach, font_size="12sp"))
        row1.add_widget(Button(text="AVATAR", on_press=self.do_pick_avatar, font_size="12sp"))
        row1.add_widget(Button(text="ADD", on_press=self.do_grab_avatar))
        row1.add_widget(Button(text="SAVE",   on_press=self.do_save))
        self.add_widget(row1)

        row1c = BoxLayout(size_hint_y=0.1)
        row1c.add_widget(Button(text="Export Avatars", on_press=self.do_export_avatars, font_size="11sp"))
        row1c.add_widget(Button(text="SCROLL", on_press=self.do_open_scroll, font_size="11sp",
                                background_color=(0.1, 0.55, 0.9, 1)))
        row1c.add_widget(Button(text="Import Avatars", on_press=self.do_import_avatars, font_size="11sp"))
        self.add_widget(row1c)

        # ----- Article popup trigger + TASK -----
        row_mode = BoxLayout(size_hint_y=0.1, spacing=4)
        self.btn_article = Button(text="📰 Article", font_size="13sp",
                                   background_color=(0.85, 0.5, 0.1, 1))
        self.btn_article.bind(on_press=lambda x: self.do_open_article_popup())
        row_mode.add_widget(self.btn_article)
        btn_task = Button(text="📋 TASK", font_size="13sp",
                          background_color=(0.3, 0.55, 0.85, 1))
        btn_task.bind(on_press=self.do_open_task_popup)
        row_mode.add_widget(btn_task)
        self.add_widget(row_mode)

        # صف خاص بالبوست المُقتبَس (Shared Post)
        row1b = BoxLayout(size_hint_y=0.15)
        row1b.add_widget(Button(text="Quote Text", on_press=self.do_quote_text))
        row1b.add_widget(Button(text="Quote Link", on_press=self.do_quote_link))
        row1b.add_widget(Button(text="Quote Img",  on_press=self.do_quote_img))
        row1b.add_widget(Button(text="Q.Avatar",   on_press=self.do_quote_avatar, font_size="12sp"))
        self.add_widget(row1b)

        # ============================================================
        # شرح الأزرار:
        #
        # Author      -> صاحب البوست عمل تعليق جديد (root). أزرق.
        #
        # NEW         -> شخص جديد دخل بتعليق مستوى أول (root) على البوست.
        #                 بداية ثريد جديد. (last_new, last_root بيتحدثوا). أبيض.
        #
        # link        -> رد على آخر تعليق حالي (current_node) بشكل مباشر.
        #                 الـ parent = current_node, reply_to = current_node.
        #                 أبيض.
        #
        # link author -> رد من صاحب البوست داخل الثريد الحالي، مرتبط
        #                 بآخر تعليق حالي (current_node) بنفس منطق link.
        #                 أزرق (نفس لون author).
        #
        # link first  -> رد على آخر تعليق "root" تم وضعه (last_root)
        #                 بغض النظر عن مكان current_node حالياً.
        #                 بيرجع بداية الثريد بدل الاستمرار في nested replies.
        #                 أبيض.
        # ============================================================
        row2 = BoxLayout(size_hint_y=0.15)
        row2.add_widget(Button(text="Author",      on_press=lambda x: self.add_root("author")))
        row2.add_widget(Button(text="NEW",         on_press=lambda x: self.add_new()))
        row2.add_widget(Button(text="link",        on_press=lambda x: self.add_link("link")))
        row2.add_widget(Button(text="link author", on_press=lambda x: self.add_link("link_author"), font_size="12sp"))
        row2.add_widget(Button(text="link first",  on_press=lambda x: self.add_link_first()))
        self.add_widget(row2)

        self.status = Label(text="", size_hint_y=0.7, halign="center", valign="middle", font_size="13sp")
        self.status.bind(size=self._update_status_text_size)
        self.add_widget(self.status)

        Clock.schedule_interval(self._safe_capture, 2)
        self.update_status()

    def _update_status_text_size(self, instance, value):
        instance.text_size = (instance.width, instance.height)

    # ----------------------------------------
    # Article popup
    # ----------------------------------------
    def do_open_article_popup(self):
        popup = ArticlePopup(on_saved=self._on_article_saved)
        popup.open()

    def _on_article_saved(self, path):
        engine.saved = True
        self.status.text = "✓ Article saved: " + path
        self.update_status()

    def _safe_capture(self, dt):
        try:
            clip = Clipboard.paste()
            if not clip or clip == engine.last_clip:
                return
            engine.last_clip = clip

            is_pure_link = bool(re.fullmatch(r'https?://\S+', clip.strip()))

            if not engine.post and not engine.post_link:
                if is_pure_link:
                    self._snapshot()
                    engine.post_link = clip
                    engine.post_time = time.time()
                else:
                    self._snapshot()
                    engine.post      = clip
                    engine.post_time = time.time()
            elif not engine.post_link and is_pure_link and not engine.quote_text:
                self._snapshot()
                engine.post_link = clip
            elif "http" in clip:
                engine.pending = clip
            else:
                engine.pending = clip
            self.update_status()
        except Exception:
            pass

    def _snapshot(self):
        engine.history.append({
            "article_data":    copy.deepcopy(engine.article_data),
            "article_url":     engine.article_url,
            "comments":        copy.deepcopy(engine.comments),
            "cur_id":          self._node_id(engine.current_node),
            "last_new_id":     self._node_id(engine.last_new),
            "last_root_id":    self._node_id(engine.last_root),
            "post":            engine.post,
            "post_images":     list(engine.post_images),
            "grabbed":         list(engine.grabbed),
            "post_link":       engine.post_link,
            "pending":         engine.pending,
            "quote_text":      engine.quote_text,
            "quote_link":      engine.quote_link,
            "quote_images":    list(engine.quote_images),
            "quote_avatar_b64":  engine.quote_avatar_b64,
            "quote_avatar_ext":  engine.quote_avatar_ext,
            "quote_author_name": engine.quote_author_name,
            "author_name":       engine.author_name,
            "author_avatar_b64": engine.author_avatar_b64,
            "author_avatar_ext": engine.author_avatar_ext,
        })
        if len(engine.history) > 20:
            engine.history.pop(0)

    def _node_id(self, node):
        return node["id"] if node else None

    def _find_by_id(self, nodes, target_id):
        for n in nodes:
            if n["id"] == target_id:
                return n
            found = self._find_by_id(n["replies"], target_id)
            if found:
                return found
        return None

    # ----------------------------------------
    # Author: تعليق جديد من صاحب البوست (root) - أزرق
    # ----------------------------------------
    def add_root(self, role):
        self._snapshot()
        engine.add_comment(engine.pending, role, parent=None)
        engine.pending = ""
        engine.saved   = False
        self.update_status()

    # ----------------------------------------
    # NEW: شخص جديد - تعليق مستوى أول (root) - أبيض
    # بداية ثريد جديد
    # ----------------------------------------
    def add_new(self):
        self._snapshot()
        engine.add_comment(engine.pending, "new", parent=None)
        engine.pending = ""
        engine.saved   = False
        self.update_status()

    # ----------------------------------------
    # link / link author: رد على التعليق الحالي (current_node) مباشرة
    # role = "link"        -> أبيض
    # role = "link_author"  -> أزرق (نفس لون author)
    # ----------------------------------------
    def add_link(self, role):
        node = engine.current_node
        if not node:
            return
        self._snapshot()
        engine.add_comment(engine.pending, role, parent=node, reply_to=node)
        engine.pending = ""
        engine.saved   = False
        self.update_status()

    # ----------------------------------------
    # link first: رد دائماً على آخر تعليق "root" تم وضعه
    # (سواء كان NEW أو Author) - بغض النظر عن مكان current_node
    # role -> "link" (أبيض) لأنه رد عادي
    # ----------------------------------------
    def add_link_first(self):
        node = engine.last_root
        if not node:
            return
        self._snapshot()
        engine.add_comment(engine.pending, "link", parent=node, reply_to=node)
        engine.pending = ""
        engine.saved   = False
        self.update_status()

    def do_quote_text(self, x):
        if not engine.pending:
            self.status.text = "No text pending."
            return
        self._snapshot()
        engine.quote_text = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_link(self, x):
        if not engine.pending:
            self.status.text = "No link pending."
            return
        self._snapshot()
        engine.quote_link = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_img(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            self.status.text = "No new images."
            return
        self._snapshot()
        engine.quote_images.extend(imgs)
        engine.grabbed.extend(imgs)
        engine.saved = False
        self.update_status()

    def do_quote_avatar(self, x):
        """جلب صورة بروفايل للبوست المقتبس - نافذة مستقلة: صورة + اسم + تأكيد"""
        imgs = engine.get_new_images()
        if not imgs:
            msg = "No new images for Quote Avatar."
            if engine.last_scan_error:
                msg += "\n(" + engine.last_scan_error + ")"
            self.status.text = msg
            return
        last_img = imgs[-1]
        engine.grabbed.append(last_img)
        ext = os.path.splitext(last_img)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            with open(last_img, "rb") as _f:
                b64_data = base64.b64encode(_f.read()).decode("utf-8")
        except Exception as e:
            self.status.text = "Error reading image: " + str(e)
            return

        captured_ext = ext

        # نافذة مستقلة: صورة + حقل اسم + زرار تأكيد فقط
        root = BoxLayout(orientation="vertical", spacing=10, padding=12)

        try:
            raw = base64.b64decode(b64_data)
            core_img = CoreImage(io.BytesIO(raw), ext=ext)
            img_widget = Image(texture=core_img.texture, size_hint_y=0.55)
            root.add_widget(img_widget)
        except Exception:
            root.add_widget(Label(text="(preview unavailable)", size_hint_y=0.55))

        name_input = TextInput(hint_text="Author name", multiline=False, size_hint_y=0.15)
        root.add_widget(name_input)

        btn_row = BoxLayout(size_hint_y=0.18, spacing=8)

        confirm_btn = Button(text="✓ Add Quote Avatar", background_color=(0.2, 0.65, 0.3, 1))
        cancel_btn  = Button(text="Cancel")

        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        qa_popup = Popup(title="Quote Avatar", content=root, size_hint=(0.78, 0.62))

        def _confirm(inst, _ext=captured_ext):
            name = name_input.text.strip()
            if not name:
                name_input.hint_text = "⚠ Name required"
                return
            self._snapshot()
            engine.quote_author_name = name
            engine.quote_avatar_b64  = b64_data
            engine.quote_avatar_ext  = _ext
            engine.saved = False
            self.update_status()
            qa_popup.dismiss()

        confirm_btn.bind(on_press=_confirm)
        cancel_btn.bind(on_press=lambda i: qa_popup.dismiss())
        qa_popup.open()

    def do_undo(self, x):
        if not engine.history:
            self.update_status()
            return
        s = engine.history.pop()
        engine.article_data    = s.get("article_data")
        engine.article_url     = s.get("article_url", "")
        engine.comments        = s["comments"]
        engine.current_node    = self._find_by_id(engine.comments, s["cur_id"]) if s["cur_id"] else None
        engine.last_new        = self._find_by_id(engine.comments, s["last_new_id"]) if s["last_new_id"] else None
        engine.last_root       = self._find_by_id(engine.comments, s["last_root_id"]) if s["last_root_id"] else None
        engine.post            = s["post"]
        engine.post_images     = s["post_images"]
        engine.grabbed         = s["grabbed"]
        engine.post_link       = s["post_link"]
        engine.pending         = s["pending"]
        engine.quote_text      = s["quote_text"]
        engine.quote_link      = s["quote_link"]
        engine.quote_images    = s["quote_images"]
        engine.quote_avatar_b64  = s["quote_avatar_b64"]
        engine.quote_avatar_ext  = s["quote_avatar_ext"]
        engine.quote_author_name = s["quote_author_name"]
        engine.author_name       = s["author_name"]
        engine.author_avatar_b64 = s["author_avatar_b64"]
        engine.author_avatar_ext = s["author_avatar_ext"]
        engine.saved = False
        self.update_status()

    def do_grab(self, x):
        imgs = engine.get_new_images()
        if imgs:
            self._snapshot()
            engine.post_images.extend(imgs)
            engine.grabbed.extend(imgs)
        self.update_status()

    def do_attach(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            return
        target = engine.current_node or (engine.comments[-1] if engine.comments else None)
        if target:
            self._snapshot()
            target["imgs"].extend(imgs)
            engine.grabbed.extend(imgs)
            engine.saved = False
        self.update_status()

    # ----------------------------------------
    # Attach Link: يضاف إلى نهاية صور البوست (post_images)
    # ----------------------------------------
    # ----------------------------------------
    # اختيار صورة البروفايل (avatar) + الاسم المرتبط بها
    # ----------------------------------------
    def do_pick_avatar(self, x):
        popup = AvatarPopup(on_select=self._set_avatar)
        popup.open()

    def _set_avatar(self, avatar):
        self._snapshot()
        engine.author_name = avatar.get("name", "")
        ext = (avatar.get("ext") or "png").lower()
        # حماية: لو الامتداد مش مدعوم (مثلاً webp قديم متخزن قبل التحويل)
        # منستخدمهوش كـ ext فعلي عشان منكسرش CoreImage بعدين عند العرض/الحفظ
        if ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
            ext = "png"
        engine.author_avatar_ext = ext
        # load b64 from file path if available
        img_path = avatar.get("path", "")
        if img_path and os.path.exists(img_path):
            try:
                with open(img_path, "rb") as _f:
                    engine.author_avatar_b64 = base64.b64encode(_f.read()).decode("utf-8")
            except Exception:
                engine.author_avatar_b64 = avatar.get("b64", "")
        else:
            engine.author_avatar_b64 = avatar.get("b64", "")
        engine.saved = False
        self.update_status()

    # ----------------------------------------
    # جلب آخر صورة جديدة من الكليبورد/الجهاز
    # ثم فتح نافذة لكتابة الاسم وإضافتها إلى AVATARS
    # ----------------------------------------
    def do_grab_avatar(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            msg = "No new images to add as avatar."
            if engine.last_scan_error:
                msg += "\n(" + engine.last_scan_error + ")"
            self.status.text = msg
            return
        last_img = imgs[-1]
        engine.grabbed.append(last_img)  # بس الأفاتار، مش كل الصور
        ext = os.path.splitext(last_img)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            with open(last_img, "rb") as _f:
                b64_data = base64.b64encode(_f.read()).decode("utf-8")
        except Exception as e:
            self.status.text = "Error reading image: " + str(e)
            return

        captured_ext = ext

        def on_confirm(name, b64, link="", destination="avatar", _ext=captured_ext):
            try:
                img_path, saved_ext = save_avatar_image(b64, _ext, name)
            except Exception as e:
                self.status.text = "❌ Image save failed: " + str(e)
                return
            new_avatar = {"name": name, "path": img_path, "ext": saved_ext, "b64": b64}

            saved_to = []
            if destination in ("avatar", "both"):
                AVATARS.append(new_avatar)
                result = save_avatars()
                if result is True:
                    saved_to.append("Avatar")
                else:
                    self.status.text = "❌ Save failed (Avatar): " + str(result)
                    return

            if destination in ("scroll", "both") and link:
                scroll_entry = dict(new_avatar)
                scroll_entry["link"] = link
                SCROLL_AVATARS.append(scroll_entry)
                result = save_scroll_avatars()
                if result is True:
                    saved_to.append("Scroll")
                else:
                    self.status.text = "❌ Save failed (Scroll): " + str(result)
                    return

            self.status.text = "✓ Saved to: " + " + ".join(saved_to) if saved_to else "❌ Not saved"
            # نضع الأفاتار كأفاتار حالي للبوست فقط لو فعلاً اتحفظ في AVATARS
            if destination in ("avatar", "both"):
                self._set_avatar(new_avatar)

        popup = NamePopup(b64_data, ext, on_confirm=on_confirm)
        popup.open()

    def do_open_scroll(self, x):
        popup = ScrollAvatarPopup(grab_avatar_cb=self.do_grab_avatar)
        popup.open()

    def do_open_task_popup(self, x):
        popup = TaskPopup()
        popup.open()

    def do_export_avatars(self, x):
        result = export_avatars()
        if result is True:
            self.status.text = "✓ Exported to: " + AVATARS_ZIP
        elif isinstance(result, str) and result.startswith("partial:"):
            missing = result[8:]
            self.status.text = "⚠ Exported (missing: " + missing + ")"
        else:
            self.status.text = "❌ Export failed: " + str(result)

    def do_import_avatars(self, x):
        def on_zip_selected(zip_path):
            result = import_avatars(zip_path)
            if result is True:
                self.status.text = "✓ Imported " + str(len(AVATARS)) + " avatars, " + str(len(TASKS)) + " tasks"
            else:
                self.status.text = "❌ Import failed: " + str(result)
        popup = ZipPickerPopup(on_select=on_zip_selected)
        popup.open()

    def do_save(self, x):
        if not engine.post and not engine.post_link:
            self.status.text = "Nothing to save yet."
            return

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="Choose save format:", font_size="14sp"))
        btn_row = BoxLayout(size_hint_y=None, height=46, spacing=8)
        html_btn = Button(text="🌐 HTML")
        md_btn = Button(text="📄 Markdown")
        both_btn = Button(text="📦 Both")
        btn_row.add_widget(html_btn)
        btn_row.add_widget(md_btn)
        btn_row.add_widget(both_btn)
        content.add_widget(btn_row)
        cancel_btn = Button(text="Cancel", size_hint_y=None, height=40)
        content.add_widget(cancel_btn)

        choice_popup = Popup(title="Save Post", content=content, size_hint=(0.85, 0.32))
        html_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("html")))
        md_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("md")))
        both_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("both")))
        cancel_btn.bind(on_press=lambda i: choice_popup.dismiss())
        choice_popup.open()

    def _avatar_save_dir(self):
        """فولدر الحفظ الخاص بالأفاتار الحالي: /sdcard/Download/<اسم_الأفاتار>/
        لو مفيش اسم أفاتار، يرجع لفولدر Download العادي."""
        base = "/sdcard/Download"
        if not os.path.isdir(base) or not os.access(base, os.W_OK):
            base = os.path.join(os.path.expanduser("~"), "Download")

        if engine.author_name:
            safe_name = re.sub(r'[^\w\-\u0600-\u06FF ]', '_', engine.author_name).strip().replace(" ", "_")
            safe_name = safe_name or "avatar"
            save_dir = os.path.join(base, safe_name)
        else:
            save_dir = base

        os.makedirs(save_dir, exist_ok=True)
        return save_dir

    def _do_save_format(self, fmt):
        save_dir = self._avatar_save_dir()

        clean = "".join(c for c in engine.post[:20] if c.isalnum() or c in " _").strip().replace(" ", "_")
        post_name = clean or "post"

        def unique_path(ext):
            p = os.path.join(save_dir, post_name + "." + ext)
            counter = 1
            while os.path.exists(p):
                p = os.path.join(save_dir, post_name + "_" + str(counter) + "." + ext)
                counter += 1
            return p

        # كاش مشترك بين HTML و Markdown لنفس عملية الحفظ:
        # في وضع "Both" كل صورة بتتضغط مرة واحدة بس وتُستخدم نتيجتها
        # في الصيغتين، بدل ما تتضغط من جديد لكل صيغة.
        img_cache = {}

        saved_paths = []
        try:
            if fmt in ("html", "both"):
                html_path = unique_path("html")
                self._write_html_file(html_path, img_cache=img_cache)
                saved_paths.append(html_path)

            if fmt in ("md", "both"):
                md_path = unique_path("md")
                self._write_md_file(md_path, img_cache=img_cache)
                saved_paths.append(md_path)

            engine.saved = True
            self.update_status()
            self.status.text = "✓ Saved:\n" + "\n".join(saved_paths)
        except Exception as e:
            self.status.text = "Error: " + str(e)

    def _write_html_file(self, path, img_cache=None):
        with open(path, "w", encoding="utf-8") as f:

                favicon_tag = ""
                if engine.author_avatar_b64:
                    fav_b64, fav_ext = compress_av_b64(engine.author_avatar_b64, engine.author_avatar_ext)
                    favicon_tag = f'<link rel="icon" type="image/{fav_ext}" href="data:image/{fav_ext};base64,{fav_b64}">\n'

                # نضغط الأفاتار مرة واحدة ونعيد استخدامه في كل مكان
                author_av_b64, author_av_ext = compress_av_b64(engine.author_avatar_b64, engine.author_avatar_ext) if engine.author_avatar_b64 else ("", "")

                f.write("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
""" + favicon_tag + """<style>
  body {
    font-family: sans-serif;
    max-width: 100%;
    margin: 0;
    padding: 12px;
    background: #f0f2f5;
    color: #050505;
    font-size: 15px;
    line-height: 1.6;
    direction: rtl;
    box-sizing: border-box;
  }
  .post {
    background: #fff;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    width: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }
  .post-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }
  .avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }
  .post-header .author-name {
    font-weight: bold;
    font-size: 15px;
    color: #050505;
  }
  .post-body img {
    max-width: 100%;
    width: 100%;
    height: auto;
    margin-top: 10px;
    border-radius: 6px;
    display: block;
  }
  .post-body {
    padding: 4px 0;
    background: #fff;
  }
  .post-body a {
    color: #1877f2;
    text-decoration: none;
    word-break: break-all;
    overflow-wrap: break-word;
    font-weight: 600;
  }
  .post-body a:hover,
  .post-body a:active {
    text-decoration: underline;
  }
  .post-link {
    font-size: 13px;
    color: #1877f2;
    margin-top: 8px;
    display: block;
    word-break: break-all;
    overflow-wrap: break-word;
    max-width: 100%;
    text-decoration: underline;
    cursor: pointer;
  }
  .post-link-box {
    border: 1px solid #ccd0d5;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 0 0 12px 0;
    background: #fff;
    text-align: center;
  }
  .post-link-box .post-link {
    margin-top: 0;
  }
  .post-images img {
    max-width: 100%;
    width: 100%;
    height: auto;
    margin-top: 10px;
    border-radius: 6px;
    display: block;
  }
  .quote-post {
    border: 1px solid #ccd0d5;
    border-radius: 8px;
    padding: 12px 14px;
    margin-top: 12px;
    background: #f7f8fa;
  }
  .quote-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .quote-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }
  .quote-author-name {
    font-weight: bold;
    font-size: 13px;
    color: #050505;
  }
  .quote-post img {
    max-width: 100%;
    margin-top: 10px;
    border-radius: 6px;
    display: block;
  }
  .quote-post .quote-link {
    font-size: 13px;
    color: #1877f2;
    margin-top: 8px;
    display: block;
    word-break: break-all;
    overflow-wrap: break-word;
    max-width: 100%;
    text-decoration: underline;
    cursor: pointer;
    text-align: center;
  }
  .comments-section {
    background: #fff;
    border-radius: 8px;
    padding: 12px 16px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.1);
  }
  .comments-title {
    font-size: 13px;
    color: #65676b;
    margin-bottom: 12px;
    font-weight: 600;
  }
  .comment-wrap {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 10px;
  }
  .comment-wrap.new-thread {
    margin-top: 14px;
    padding-top: 10px;
    border-top: 2px solid #c5c8ce;
  }
  .comment-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    margin-top: 2px;
  }
  .comment-body {
    display: flex;
    flex-direction: column;
  }
  .comment-name {
    font-size: 12px;
    font-weight: bold;
    margin-bottom: 2px;
    color: #050505;
  }
  .comment-bubble {
    border-radius: 18px;
    padding: 8px 14px;
    font-size: 14px;
    background: #ffffff;
    border: 1px solid #e4e6eb;
  }
  .comment-bubble img {
    max-width: 100%;
    border-radius: 8px;
    margin-top: 6px;
    display: block;
  }
  .comment-bubble a {
    color: #1877f2;
    text-decoration: none;
    cursor: pointer;
    word-break: break-all;
    overflow-wrap: break-word;
    max-width: 100%;
    display: inline;
    font-weight: 600;
  }
  .comment-bubble a:hover,
  .comment-bubble a:active {
    text-decoration: underline;
  }
  .replies-toggle {
    background: none;
    border: none;
    color: #65676b;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    padding: 4px 8px;
    margin-bottom: 4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .replies-toggle:hover {
    text-decoration: underline;
  }
  .replies-toggle .arrow {
    display: inline-block;
    transition: transform 0.15s ease;
  }
  .replies-toggle.collapsed .arrow {
    transform: rotate(-90deg);
  }
  .replies.collapsed {
    display: none;
  }

  /* author و link_author = أزرق فاتح + bold */
  .comment-bubble.author,
  .comment-bubble.link_author {
    background: #e7f3ff;
    border: 1px solid #b0d0f0;
    font-weight: bold;
  }

  .replies {
    margin-right: 0;
    margin-left: 0;
    margin-top: 0;
    position: relative;
    padding-left: 0;
    padding-right: 44px;
  }
  .replies::before {
    content: "";
    position: absolute;
    top: 0;
    right: 20px;
    width: 2px;
    height: calc(100% - 20px);
    background: #ced0d4;
    border-radius: 2px;
  }
  .replies > .comment-wrap {
    position: relative;
    margin-bottom: 6px;
  }
</style>
</head>
<body>
""")

                # ----- Post Header (avatar + اسم) -----
                f.write('<div class="post">\n')
                if author_av_b64 or engine.author_name:
                    f.write('<div class="post-header">\n')
                    if author_av_b64:
                        f.write(f'<img class="avatar" src="data:image/{author_av_ext};base64,{author_av_b64}">\n')
                    if engine.author_name:
                        f.write(f'<div class="author-name">{_html.escape(engine.author_name)}</div>\n')
                    f.write('</div>\n')

                URL_RE_POST = re.compile(r'(https?://[^\s<]+)')
                post_html = URL_RE_POST.sub(r'<a href="\1" target="_blank">\1</a>', _html.escape(engine.post).replace("\n", "<br>"))
                f.write(f'<div class="post-body">{post_html}</div>\n')

                if engine.post_images:
                    f.write('<div class="post-images">\n')
                    for img in engine.post_images:
                        b64, ext = compress_to_b64_cached(img, img_cache)
                        if b64:
                            f.write(f'<img src="data:image/{ext};base64,{b64}">\n')
                    f.write('</div>\n')

                if engine.quote_text or engine.quote_link or engine.quote_images:
                    f.write('<div class="quote-post">\n')
                    if engine.quote_avatar_b64 or engine.quote_author_name:
                        f.write('<div class="quote-header">\n')
                        if engine.quote_avatar_b64:
                            q_b64, q_ext = compress_av_b64(engine.quote_avatar_b64, engine.quote_avatar_ext)
                            f.write(f'<img class="quote-avatar" src="data:image/{q_ext};base64,{q_b64}">\n')
                        if engine.quote_author_name:
                            f.write(f'<div class="quote-author-name">{_html.escape(engine.quote_author_name)}</div>\n')
                        f.write('</div>\n')
                    if engine.quote_text:
                        quote_html = URL_RE_POST.sub(r'<a href="\1" target="_blank">\1</a>', _html.escape(engine.quote_text).replace("\n", "<br>"))
                        f.write(f'<div>{quote_html}</div>\n')
                    for img in engine.quote_images:
                        b64, ext = compress_to_b64_cached(img, img_cache)
                        if b64:
                            f.write(f'<img src="data:image/{ext};base64,{b64}">\n')
                    if engine.quote_link:
                        f.write(f'<a class="quote-link" href="{engine.quote_link}">{engine.quote_link}</a>\n')
                    f.write('</div>\n')

                f.write('</div>\n')  # post

                if engine.post_link:
                    f.write('<div class="post-link-box">\n')
                    f.write(f'<a class="post-link" href="{engine.post_link}">{engine.post_link}</a>\n')
                    f.write('</div>\n')

                f.write('<div class="comments-section">\n')
                f.write('<div class="comments-title">Comments</div>\n')

                URL_RE = re.compile(r'(https?://[^\s<]+)')

                def linkify(text):
                    return URL_RE.sub(r'<a href="\1" target="_blank">\1</a>', _html.escape(text))

                def write_tree(nodes, is_root=True):
                    for idx, n in enumerate(nodes):
                        role = n["role"]
                        if role in ("author", "link_author", "new", "link"):
                            css = role
                        else:
                            css = "link"

                        text = linkify(n["text"]).replace("\n", "<br>")
                        is_owner = role in ("author", "link_author")
                        show_identity = True

                        wrap_class = "comment-wrap"
                        if is_root and idx > 0:
                            wrap_class += " new-thread"

                        f.write(f'<div class="{wrap_class}">\n')
                        if is_owner and author_av_b64 and show_identity:
                            f.write(f'<img class="comment-avatar" src="data:image/{author_av_ext};base64,{author_av_b64}">\n')
                        f.write('<div class="comment-body">\n')
                        if is_owner and engine.author_name and show_identity:
                            f.write(f'<div class="comment-name">{_html.escape(engine.author_name)}</div>\n')
                        f.write(f'<div class="comment-bubble {css}">{text}')
                        for img in n["imgs"]:
                            b64, ext = compress_to_b64_cached(img, img_cache)
                            if b64:
                                f.write(f'<img src="data:image/{ext};base64,{b64}">')
                        f.write('</div>\n')
                        f.write('</div>\n')  # comment-body
                        f.write('</div>\n')  # comment-wrap

                        if n["replies"]:
                            rid = "rep_" + str(n["id"])
                            count = self._count_all(n["replies"])
                            f.write(f'<button class="replies-toggle" data-target="{rid}" onclick="toggleReplies(this)">'
                                    f'<span class="arrow">&#9660;</span>{count} ' + ("replies" if count != 1 else "reply") + '</button>\n')
                            f.write(f'<div class="replies" id="{rid}">\n')
                            write_tree(n["replies"], is_root=False)
                            f.write('</div>\n')

                write_tree(engine.comments)
                f.write('''</div>
<script>
function toggleReplies(btn) {
  var id = btn.getAttribute('data-target');
  var box = document.getElementById(id);
  if (!box) return;
  box.classList.toggle('collapsed');
  btn.classList.toggle('collapsed');
}
</script>
</body></html>''')

    def _write_md_file(self, path, img_cache=None):
        """يحفظ نفس بيانات البوست/الكومنتات بصيغة Markdown.
        الصور تُحفظ كملفات فعلية في فولدر images/ بجوار ملف الـ md."""
        save_dir = os.path.dirname(path)
        base_name = os.path.splitext(os.path.basename(path))[0]
        img_dir = os.path.join(save_dir, "images")

        img_counter = [0]

        def save_img_md(src_path):
            b64, ext = compress_to_b64_cached(src_path, img_cache)
            if not b64:
                return None
            os.makedirs(img_dir, exist_ok=True)
            img_counter[0] += 1
            fname = f"{base_name}_{img_counter[0]}.{ext}"
            fpath = os.path.join(img_dir, fname)
            with open(fpath, "wb") as imf:
                imf.write(base64.b64decode(b64))
            return os.path.join("images", fname)

        lines = []

        if engine.author_name:
            lines.append(f"**{engine.author_name}**")
            lines.append("")

        if engine.post:
            lines.append(engine.post.strip())
            lines.append("")

        for img in engine.post_images:
            rel = save_img_md(img)
            if rel:
                lines.append(f"![]({rel})")
        if engine.post_images:
            lines.append("")

        if engine.post_link:
            lines.append(f"🔗 {engine.post_link}")
            lines.append("")

        if engine.quote_text or engine.quote_link or engine.quote_images:
            lines.append("> ---")
            if engine.quote_author_name:
                lines.append(f"> **{engine.quote_author_name}**")
            if engine.quote_text:
                for qline in engine.quote_text.strip().split("\n"):
                    lines.append(f"> {qline}")
            for img in engine.quote_images:
                rel = save_img_md(img)
                if rel:
                    lines.append(f"> ![]({rel})")
            if engine.quote_link:
                lines.append(f"> 🔗 {engine.quote_link}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Comments")
        lines.append("")

        def write_tree_md(nodes, depth=0):
            indent = "  " * depth
            for n in nodes:
                role = n["role"]
                prefix = "👤 " if role in ("author", "link_author") else ""
                name_line = f"{indent}- {prefix}{n['text']}".rstrip()
                lines.append(name_line)
                for img in n["imgs"]:
                    rel = save_img_md(img)
                    if rel:
                        lines.append(f"{indent}  ![]({rel})")
                if n["replies"]:
                    write_tree_md(n["replies"], depth + 1)

        write_tree_md(engine.comments)

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def update_status(self):
        attach_count   = self._count_imgs(engine.comments)
        total_comments = self._count_all(engine.comments)
        cur = engine.current_node["role"] if engine.current_node else "-"

        def b(val):
            return "1" if val else "0"

        def row(a, b_, c):
            return f"{a:<18}{b_:<18}{c}"

        lines = [
            row(f"POST: {b(engine.post)}",
                f"LINK: {b(engine.post_link)}",
                f"IMAGE: {len(engine.post_images)}"),
            "",
            row(f"QUOTE: {b(engine.quote_text)}",
                f"Q.LINK: {b(engine.quote_link)}",
                f"Q.IMG: {len(engine.quote_images)}"),
            f"Q.AVATAR: {engine.quote_author_name or '-'}",
            "",
            row(f"COMMENTS: {total_comments}",
                f"LAST: {cur}",
                f"ATTACH: {attach_count}"),
            "",
            f"AVATAR: {engine.author_name or '-'}",
            "-" * 12,
            f"SAVED: {'YES' if engine.saved else 'NO'}",
        ]

        self.status.text = "\n".join(lines)

    def _count_all(self, nodes):
        total = 0
        for n in nodes:
            total += 1
            total += self._count_all(n["replies"])
        return total

    def _count_imgs(self, nodes):
        total = 0
        for n in nodes:
            total += len(n["imgs"])
            total += self._count_imgs(n["replies"])
        return total

    def do_reset(self, x):
        engine.reset()
        self.update_status()


class MyApp(App):
    def build(self):
        request_android_permissions()
        self._request_manage_storage()
        return UI()

    def _request_manage_storage(self):
        """أندرويد 11+ يحتاج MANAGE_EXTERNAL_STORAGE يتفتح من الإعدادات"""
        try:
            from android.permissions import check_permission, Permission
            from jnius import autoclass
            if not hasattr(Permission, "MANAGE_EXTERNAL_STORAGE"):
                return
            if check_permission(Permission.MANAGE_EXTERNAL_STORAGE):
                return
            Environment = autoclass("android.os.Environment")
            if Environment.isExternalStorageManager():
                return
            Intent = autoclass("android.content.Intent")
            Settings = autoclass("android.provider.Settings")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
            intent.setData(Uri.parse("package:" + PythonActivity.mActivity.getPackageName()))
            PythonActivity.mActivity.startActivity(intent)
        except Exception:
            pass

    def on_start(self):
        global AVATARS, SCROLL_AVATARS, TASKS
        AVATARS.extend(load_avatars())
        SCROLL_AVATARS.extend(load_scroll_avatars())
        TASKS.extend(load_tasks())


MyApp().run()

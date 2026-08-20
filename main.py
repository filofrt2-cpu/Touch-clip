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

_AVATAR_STORE_MAX_PX = 600  # أقصى بعد للصورة المحفوظة فعليًا على الديسك لكل أفاتار

def save_avatar_image(b64_data, ext, name):
    """حفظ الصورة كملف منفصل وإرجاع (المسار, الامتداد)
    ملحوظة: لو الصورة webp بنحولها لـ png عشان Kivy CoreImage
    مش بيقدر يفتح webp على أغلب بيلدات الأندرويد، وده كان سبب الـ crash
    لما يفتح Avatar تاني مرة.
    كمان بنصغّر أي صورة أكبر من _AVATAR_STORE_MAX_PX قبل الحفظ عشان الصور
    الخام (من الكاميرا مثلاً) متاخدش مساحة ديسك كبيرة من غير داعي - الأفاتار
    أصلاً بيتعرض صغير في كل الشاشات، فمفيش فايدة من الاحتفاظ بدقة عالية."""
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

    if HAS_PIL:
        try:
            img = PilImage.open(io.BytesIO(raw))
            w, h = img.size
            if max(w, h) > _AVATAR_STORE_MAX_PX:
                scale = _AVATAR_STORE_MAX_PX / float(max(w, h))
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                img = img.resize(new_size, PilImage.LANCZOS)
                buf = io.BytesIO()
                if ext.lower() in ("jpg", "jpeg"):
                    img.convert("RGB").save(buf, format="JPEG", quality=85)
                elif ext.lower() == "png":
                    img.save(buf, format="PNG", optimize=True)
                else:
                    img.save(buf, format=ext.upper())
                raw = buf.getvalue()
        except Exception:
            pass  # لو التصغير فشل لأي سبب، نحفظ الصورة الأصلية زي ما هي

    filename = safe_name + "_" + str(int(time.time())) + "." + ext
    path = os.path.join(AVATARS_DIR, filename)
    with open(path, "wb") as f:
        f.write(raw)
    return path, ext

# =========================
# THUMBNAILS (نسخة مصغّرة لكل أفاتار)
# المشكلة: كل أفاتار كانت بتتخزن مرتين - كملف كامل الحجم على الديسك،
# وبرضه كـ base64 كامل الحجم جوه avatars.json نفسه. مع ١٠٠ أفاتار بصور
# موبايل حديثة، ده بيخلي avatars.json ضخم جدًا (ممكن مئات الميجا نص)،
# وكل فتح تطبيق بيقرا الملف ده كامل + يفك تشفير كل صورة بحجمها الأصلي
# بس عشان يعرضها في خانة صغيرة ٨٨ بكسل. الحل: نبني نسخة مصغّرة مرة واحدة
# ونخزّنها هي اللي بتتعرض في القوائم، والصورة الأصلية تفضل للاستخدام
# الفعلي بس (لما تختار الأفاتار عشان يدخل في البوست النهائي).
# =========================
_THUMB_MAX_SIZE = 200  # أقصى بعد (بكسل) للنسخة المصغّرة

def make_thumbnail_b64(raw_bytes, ext):
    """يبني نسخة مصغّرة من bytes الصورة الأصلية، يرجع (thumb_b64, thumb_ext).
    لو PIL مش متاح أو حصل خطأ، يرجع (None, None) والكود اللي بينادي عليها
    هيقع على الصورة الأصلية بدل ما ينهار."""
    if not HAS_PIL:
        return None, None
    try:
        img = PilImage.open(io.BytesIO(raw_bytes))
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((_THUMB_MAX_SIZE, _THUMB_MAX_SIZE))
        buf = io.BytesIO()
        if has_alpha:
            img.save(buf, format="PNG")
            save_ext = "png"
        else:
            img.save(buf, format="JPEG", quality=70)
            save_ext = "jpeg"
        return base64.b64encode(buf.getvalue()).decode("utf-8"), save_ext
    except Exception:
        return None, None

def get_avatar_raw_bytes(av):
    """يرجع bytes الصورة الأصلية الكاملة (من الملف لو موجود، وإلا من b64)."""
    img_path = av.get("path", "")
    if img_path and os.path.exists(img_path):
        try:
            with open(img_path, "rb") as f:
                return f.read()
        except Exception:
            pass
    try:
        return base64.b64decode(av.get("b64", "") or "")
    except Exception:
        return None

def slim_legacy_avatar_blobs(items, save_fn):
    """تنظيف لمرة واحدة للبيانات القديمة: لو الأفاتار عنده path شغال والملف
    موجود فعلاً على الديسك، مفيش داعي نفضل محتفظين بنسخة base64 كاملة من
    نفس الصورة جوه الملف (avatars.json/scroll_avatars.json/tasks.json).
    ده التكرار اللي كان بيخلي الملفات دي ضخمة وبطيئة القراءة كل ما
    التطبيق يفتح. بيرجع True لو حصل تغيير فعلي (عشان نحفظ مرة واحدة بس)."""
    changed = False
    for av in items:
        p = av.get("path", "")
        if p and os.path.exists(p) and av.get("b64"):
            av["b64"] = ""
            changed = True
    if changed and save_fn:
        save_fn()
    return changed

def export_avatars():
    try:
        with zipfile.ZipFile(AVATARS_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(AVATARS_FILE):
                zf.write(AVATARS_FILE, "avatars.json")
            # نصدّر الفورمات الجديد (القوائم المتعددة). ملف scroll_avatars.json
            # القديم بقى مش بيتحدّث (save_scroll_avatars بقت بتحفظ scroll_lists.json
            # بدله)، فمنعتمدش عليه هنا عشان مايبقاش فيه نسخة قديمة مضللة.
            save_scroll_lists()
            if os.path.exists(SCROLL_LISTS_FILE):
                zf.write(SCROLL_LISTS_FILE, "scroll_lists.json")
            if os.path.exists(TASKS_FILE):
                zf.write(TASKS_FILE, "tasks.json")
            missing = []
            for av in AVATARS:
                img_path = av.get("path", "")
                if img_path and os.path.exists(img_path):
                    zf.write(img_path, os.path.basename(img_path))
                elif img_path:
                    missing.append(os.path.basename(img_path))
            # صور كل القوائم في الـ Scroll (مش القائمة النشطة بس)
            for lst in SCROLL_LISTS:
                for av in lst.get("avatars", []):
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
        # تنظيف فوري: شيل تكرار الـ base64 الكامل لو الملف الأصلي موجود فعلاً
        # على الديسك بعد فك الـ ZIP - مش لازم ننتظر إعادة فتح التطبيق
        slim_legacy_avatar_blobs(AVATARS, None)
        save_avatars()
        # استيراد Scroll (بيقرا الفورمات الجديد scroll_lists.json لو موجود
        # جوه الـ ZIP، وإلا يعمل migration من الفورمات القديم تلقائيًا)
        global SCROLL_ACTIVE_LIST
        loaded_lists, loaded_active = load_scroll_lists()
        for lst in loaded_lists:
            for av in lst.get("avatars", []):
                if av.get("path"):
                    av["path"] = os.path.join(AVATARS_DIR, os.path.basename(av["path"]))
        SCROLL_LISTS.clear()
        SCROLL_LISTS.extend(loaded_lists)
        SCROLL_ACTIVE_LIST = loaded_active
        sync_scroll_avatars_ref()
        for lst in SCROLL_LISTS:
            slim_legacy_avatar_blobs(lst.get("avatars", []), None)
        save_scroll_lists()
        # استيراد Tasks (المهام بكل ما فيها من أفاتارات)
        loaded_tasks = load_tasks()
        for task in loaded_tasks:
            for item in task.get("items", []):
                if "path" in item and item["path"]:
                    item["path"] = os.path.join(AVATARS_DIR, os.path.basename(item["path"]))
            slim_legacy_avatar_blobs(task.get("items", []), None)
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
SCROLL_LISTS_FILE = "/sdcard/Download/touchclip_avatars/scroll_lists.json"

def load_scroll_avatars():
    """الفورمات القديم (Flat list واحدة) - محتفظين بيها بس عشان الـ migration
    وقراءة نسخ احتياطية قديمة (ZIP export قبل ميزة القوائم المتعددة)."""
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

def load_scroll_lists():
    """يرجّع (lists, active_index). بيقرا الفورمات الجديد (قوائم متعددة) لو
    موجود، وإلا يعمل migration تلقائي من الفورمات القديم (scroll_avatars.json
    كـ Flat list) لقائمة واحدة اسمها 'List 1'."""
    try:
        if os.path.exists(SCROLL_LISTS_FILE):
            with open(SCROLL_LISTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            lists = [l for l in (data.get("lists") or []) if isinstance(l, dict)]
            for l in lists:
                l.setdefault("name", "List")
                l.setdefault("avatars", [])
            if not lists:
                lists = [{"name": "List 1", "avatars": []}]
            active = data.get("active", 0)
            if not isinstance(active, int) or not (0 <= active < len(lists)):
                active = 0
            return lists, active
    except Exception:
        try:
            if os.path.exists(SCROLL_LISTS_FILE):
                backup = SCROLL_LISTS_FILE + ".corrupted_" + str(int(time.time()))
                os.replace(SCROLL_LISTS_FILE, backup)
        except Exception:
            pass
    # مفيش ملف بالفورمات الجديد - نجرب migration من الفلات القديم
    legacy = load_scroll_avatars()
    return [{"name": "List 1", "avatars": legacy}], 0

def save_scroll_lists():
    try:
        ensure_avatars_dir()
        tmp = SCROLL_LISTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"lists": SCROLL_LISTS, "active": SCROLL_ACTIVE_LIST}, f, ensure_ascii=False)
        os.replace(tmp, SCROLL_LISTS_FILE)
        return True
    except Exception as e:
        return str(e)

# توافق مع الكود القديم: أي مكان بينادي save_scroll_avatars() بقى فعليًا
# بيحفظ هيكل القوائم كله (SCROLL_LISTS + SCROLL_ACTIVE_LIST).
def save_scroll_avatars():
    return save_scroll_lists()

SCROLL_LISTS = []       # [{"name": "List 1", "avatars": [...]}, {"name": "List 2", "avatars": [...]}, ...]
SCROLL_ACTIVE_LIST = 0  # index القائمة المفتوحة حاليًا في الـ Scroll popup

def sync_scroll_avatars_ref():
    """يحدّث SCROLL_AVATARS عشان يبقى مشاور على avatars بتاعة القائمة النشطة
    حاليًا. أي كود قديم بيتعامل مع SCROLL_AVATARS مباشرة (append/pop/clear)
    هيفضل شغال صح لأنه بيعدّل على نفس الـ object المخزّن جوه SCROLL_LISTS.
    لازم تتنادى بعد أي تغيير في SCROLL_ACTIVE_LIST أو في عدد/ترتيب القوائم."""
    global SCROLL_AVATARS, SCROLL_ACTIVE_LIST
    if not SCROLL_LISTS:
        SCROLL_LISTS.append({"name": "List 1", "avatars": []})
    if not (0 <= SCROLL_ACTIVE_LIST < len(SCROLL_LISTS)):
        SCROLL_ACTIVE_LIST = 0
    SCROLL_AVATARS = SCROLL_LISTS[SCROLL_ACTIVE_LIST]["avatars"]

SCROLL_AVATARS = []

# =========================
# AVATAR2_LISTS: نفس فكرة SCROLL_LISTS/TASKS بالظبط - قائمة قوائم أفاتارات
# مستقلة تمامًا عن AVATAR الأساسي. مافيش "active list" هنا لأن التنقل
# بيتم بالكامل عن طريق NamedAvatarListsPopup (زي Task).
# =========================
AVATAR2_LISTS_FILE = "/sdcard/Download/touchclip_avatars/avatar2_lists.json"
AVATAR2_LISTS = []   # [{"name": "List 1", "avatars": [...]}, ...]

def load_avatar2_lists():
    try:
        if os.path.exists(AVATAR2_LISTS_FILE):
            with open(AVATAR2_LISTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            lists = [l for l in (data.get("lists") or []) if isinstance(l, dict)]
            for l in lists:
                l.setdefault("name", "List")
                l.setdefault("avatars", [])
            return lists
    except Exception:
        try:
            if os.path.exists(AVATAR2_LISTS_FILE):
                backup = AVATAR2_LISTS_FILE + ".corrupted_" + str(int(time.time()))
                os.replace(AVATAR2_LISTS_FILE, backup)
        except Exception:
            pass
    return []

def save_avatar2_lists():
    try:
        ensure_avatars_dir()
        tmp = AVATAR2_LISTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"lists": AVATAR2_LISTS}, f, ensure_ascii=False)
        os.replace(tmp, AVATAR2_LISTS_FILE)
        return True
    except Exception as e:
        return str(e)
sync_scroll_avatars_ref()


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

LINK_PREVIEW_DIR = "/sdcard/Download/touchclip_avatars/link_previews"


def fetch_link_preview(url):
    """معاينة لينك زي Raindrop.io: بيجيب og:image (وog:title لو موجود)
    وينزّل الصورة على الجهاز، ويرجّع {"image_path":.., "title":..}
    أو {"error":..} لو فشل."""
    if not HAS_ARTICLE_DEPS:
        return {"error": "requests/beautifulsoup4 not installed in this build."}
    try:
        resp = requests.get(url, headers=ARTICLE_HEADERS, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        def get_meta(prop):
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            return tag["content"].strip() if tag and tag.get("content") else None

        title = get_meta("og:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()

        img_url = get_meta("og:image") or get_meta("twitter:image")
        if not img_url:
            return {"error": "No preview image found for this link.", "title": title}
        img_url = urljoin(url, img_url.strip())

        img_resp = requests.get(img_url, headers=ARTICLE_HEADERS, timeout=12, stream=True)
        img_resp.raise_for_status()

        ext = os.path.splitext(img_url.split("?")[0])[1].lower().lstrip(".")
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            ext = "jpg"

        os.makedirs(LINK_PREVIEW_DIR, exist_ok=True)
        fname = "preview_" + str(int(time.time() * 1000)) + "." + ext
        fpath = os.path.join(LINK_PREVIEW_DIR, fname)
        with open(fpath, "wb") as f:
            for chunk in img_resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
            return {"error": "Downloaded preview image is empty.", "title": title}

        return {"image_path": fpath, "title": title}
    except Exception as e:
        return {"error": str(e)}


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
                   "/sdcard/Pictures", "/sdcard/Pictures/WhatsApp Images",
                   "/sdcard/WhatsApp/Media/WhatsApp Images", "/sdcard/Pictures/Telegram",
                   "/sdcard/Telegram/Telegram Images", "/sdcard/Pictures/Messenger",
                   "/sdcard/Pictures/Instagram"]
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


def get_latest_image_anywhere(exclude=None):
    """
    يحاول يجيب آخر صورة اتضافت فعليًا لجهاز الأندرويد (أي فولدر/أي تطبيق:
    واتساب، تيليجرام، الكاميرا، فيسبوك...) عن طريق MediaStore، بدل الاقتصار
    على قائمة فولدرات ثابتة (زي فولدر Facebook بس). لو مش شغال على أندرويد
    أو حصل أي خطأ (صلاحيات، بيئة الاختبار...)، بيرجع None ونرجع لطريقة
    الفولدرات القديمة (get_new_images) كـ fallback.
    """
    exclude = exclude or set()
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        resolver = activity.getContentResolver()
        MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
        ImagesMedia = autoclass("android.provider.MediaStore$Images$Media")
        uri = ImagesMedia.EXTERNAL_CONTENT_URI
        projection = [MediaColumns.DATA]
        sort_order = MediaColumns.DATE_ADDED + " DESC"
        cursor = resolver.query(uri, projection, None, None, sort_order)
        if cursor is None:
            return None
        try:
            data_idx = cursor.getColumnIndexOrThrow(MediaColumns.DATA)
            while cursor.moveToNext():
                path = cursor.getString(data_idx)
                if path and path not in exclude and os.path.exists(path):
                    return path
            return None
        finally:
            cursor.close()
    except Exception:
        return None


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
# AVATAR TEXTURE CACHE
# كاش عالمي للـ textures عشان مايتحملوش من الديسك أكتر من مرة
# =========================
_AVATAR_TEXTURE_CACHE = {}  # cache_key -> texture
_AVATARS_DIRTY = False      # فيه thumbnails جديدة اتبنت في الذاكرة ولسه ما اتحفظتش على الديسك


def _load_avatar_texture(av, thumb=True):
    """يحمّل texture الأفاتار مع cache.

    thumb=True (الافتراضي، مستخدم في شبكات الاختيار Avatar/Scroll/Task):
        يستخدم نسخة مصغّرة 200px. لو مش موجودة في الأفاتار، يبنيها الآن
        من الصورة الأصلية (مرة واحدة بس) ويعلّم _AVATARS_DIRTY عشان تتحفظ
        دفعة واحدة بعد ما القائمة تخلص تحميل (مش بعد كل صورة على حدة).

    thumb=False: يحمّل الصورة الأصلية بالجودة الكاملة - يُستخدم بس وقت
        الاختيار الفعلي للأفاتار عشان الجودة الكاملة تدخل في البوست."""
    global _AVATARS_DIRTY

    if thumb:
        cache_key = "thumb:" + (av.get("path") or ("b64:" + av.get("b64", "")[:32]))
        if cache_key in _AVATAR_TEXTURE_CACHE:
            return _AVATAR_TEXTURE_CACHE[cache_key]

        thumb_b64 = av.get("thumb_b64")
        thumb_ext = av.get("thumb_ext")
        if not thumb_b64:
            raw = get_avatar_raw_bytes(av)
            if raw:
                thumb_b64, thumb_ext = make_thumbnail_b64(raw, av.get("ext") or "png")
                if thumb_b64:
                    av["thumb_b64"] = thumb_b64
                    av["thumb_ext"] = thumb_ext
                    _AVATARS_DIRTY = True

        if thumb_b64:
            try:
                raw = base64.b64decode(thumb_b64)
                core_img = CoreImage(io.BytesIO(raw), ext=(thumb_ext or "jpeg"))
                texture = core_img.texture
                _AVATAR_TEXTURE_CACHE[cache_key] = texture
                return texture
            except Exception:
                pass
        # لو مفيش PIL أو التصغير فشل، نكمل تحت ونحمّل الصورة الأصلية
        # بدل ما نعرض علامة استفهام فاضية

    cache_key = av.get("path") or ("b64:" + av.get("b64", "")[:32])
    if cache_key in _AVATAR_TEXTURE_CACHE:
        return _AVATAR_TEXTURE_CACHE[cache_key]
    try:
        img_path = av.get("path", "")
        img_ext = (av.get("ext") or "png").lower()
        if img_ext not in ("png", "jpg", "jpeg", "gif", "bmp"):
            img_ext = "jpeg"
        if img_path and os.path.exists(img_path):
            core_img = CoreImage(img_path, ext=img_ext)
        else:
            raw = base64.b64decode(av["b64"])
            core_img = CoreImage(io.BytesIO(raw), ext=img_ext)
        texture = core_img.texture
        _AVATAR_TEXTURE_CACHE[cache_key] = texture
        return texture
    except Exception:
        return None


def flush_avatar_thumbnails_if_dirty():
    """يحفظ الـ thumbnails الجديدة اللي اتبنت في الذاكرة على الديسك -
    يُستدعى مرة واحدة بعد ما شبكة الأفاتارات تخلص تحميل بالكامل،
    مش بعد كل صورة (عشان منعملش كتابة ديسك ١٠٠ مرة متتالية)."""
    global _AVATARS_DIRTY
    if _AVATARS_DIRTY:
        save_avatars()
        save_scroll_avatars()
        _AVATARS_DIRTY = False


# =========================
# DragCell: زرار صورة الأفاتار العادي + ضغط مطوّل (long-press) + سحب
# لإعادة الترتيب. التاب العادي (pick / open link) يفضل شغال زي ما هو
# بالظبط لأننا بننادي super() الأول في كل touch method، فمفيش أي تغيير
# على السلوك الحالي غير إضافة اللونج-برس فوقه.
# =========================
class DragCell(Button):
    _LONG_PRESS_SEC = 0.45
    _MOVE_CANCEL_PX = 25

    def __init__(self, idx, on_long_press=None, on_drag_move=None, on_drag_end=None,
                 arrange_mode=False, **kwargs):
        super().__init__(**kwargs)
        self.idx = idx
        self.on_long_press = on_long_press
        self.on_drag_move = on_drag_move
        self.on_drag_end = on_drag_end
        self.arrange_mode = arrange_mode
        self._lp_ev = None
        self._dragging = False
        self._start_pos = None

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if handled and self.collide_point(*touch.pos) and self.on_long_press:
            self._start_pos = touch.pos
            if self.arrange_mode:
                # وضع Arrange مفعّل: السحب يشتغل فورًا من غير استنى long-press
                # (بيفيد لو long-press مش شغال على الجهاز)
                self._dragging = True
                self.on_long_press(self.idx, touch)
            else:
                self._dragging = False
                self._lp_ev = Clock.schedule_once(lambda dt: self._fire_long_press(touch), self._LONG_PRESS_SEC)
        return handled

    def _fire_long_press(self, touch):
        self._lp_ev = None
        if touch.grab_current is self:
            self._dragging = True
            self.on_long_press(self.idx, touch)

    def on_touch_move(self, touch):
        handled = super().on_touch_move(touch)
        if touch.grab_current is self:
            if self._dragging and self.on_drag_move:
                self.on_drag_move(touch)
            elif self._lp_ev and self._start_pos:
                dx = abs(touch.pos[0] - self._start_pos[0])
                dy = abs(touch.pos[1] - self._start_pos[1])
                if dx > self._MOVE_CANCEL_PX or dy > self._MOVE_CANCEL_PX:
                    self._lp_ev.cancel()
                    self._lp_ev = None
        return handled

    def on_touch_up(self, touch):
        if self._lp_ev:
            self._lp_ev.cancel()
            self._lp_ev = None
        was_dragging = self._dragging
        self._dragging = False
        if was_dragging and touch.grab_current is self:
            if self.on_drag_end:
                self.on_drag_end(touch)
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)


# =========================
# AVATAR PICKER POPUP
# =========================
class AvatarPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = ""
        self.separator_height = 0
        self.size_hint = (0.9, 0.9)
        self.on_select = on_select
        self._drag_idx = None
        self._drag_ref = None
        self._arrange_mode = False

        self.root_layout = BoxLayout(orientation="vertical")

        top_row = BoxLayout(size_hint_y=None, height=44, spacing=6, padding=(8, 2))
        title_lbl = Label(text="Choose Avatar", font_size="16sp", bold=True,
                          halign="left", valign="middle")
        title_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        self.arrange_btn = Button(text="⇕", font_size="18sp", size_hint=(None, None),
                                   size=(44, 40), background_color=(0.5, 0.5, 0.5, 1))
        self.arrange_btn.bind(on_press=lambda x: self._toggle_arrange())
        top_row.add_widget(title_lbl)
        top_row.add_widget(self.arrange_btn)
        self.root_layout.add_widget(top_row)

        self.scroll = ScrollView(size_hint_y=1)
        self.grid_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self.grid_container.bind(minimum_height=self.grid_container.setter("height"))
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout

        # تحميل lazy بعد frame واحد عشان الـ popup يفتح فورًا
        Clock.schedule_once(lambda dt: self._refresh_grid(), 0)

    def _refresh_grid(self):
        global AVATARS
        # لا تحمّل من الديسك لو البيانات موجودة أصلاً في الذاكرة
        if not AVATARS:
            fresh = load_avatars()
            AVATARS.clear()
            AVATARS.extend(fresh)

        self.grid_container.clear_widgets()
        if not AVATARS:
            self.grid_container.add_widget(
                Label(text="No avatars yet.\nUse ADD to add avatars.", size_hint_y=None, height=80)
            )
            return

        from kivy.uix.floatlayout import FloatLayout
        self._av_all = list(AVATARS)
        self._av_grid = GridLayout(cols=5, size_hint_y=None, spacing=4, padding=4)
        self._av_grid.bind(minimum_height=self._av_grid.setter("height"))
        self.grid_container.add_widget(self._av_grid)
        self._load_av_batch(0)

    def _load_av_batch(self, start, batch=8):
        """يحمّل batch من الأفاتارات ثم يجدول الـ batch التالية — الـ popup يظهر فوراً"""
        from kivy.uix.floatlayout import FloatLayout
        avatars = self._av_all
        end = min(start + batch, len(avatars))

        for idx in range(start, end):
            av = avatars[idx]
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=146)

            texture = _load_avatar_texture(av)
            if texture:
                img_widget = Image(texture=texture, size_hint=(1, 1))
            else:
                img_widget = Label(text="?", size_hint=(1, 1))

            float_cell = FloatLayout(size_hint_y=None, height=88)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = DragCell(idx, on_long_press=self._drag_start, on_drag_move=self._drag_move,
                              on_drag_end=self._drag_end, arrange_mode=self._arrange_mode,
                              size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                              background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, i=idx: self._pick(i))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            cell.add_widget(float_cell)

            # اسم الأفاتار — الضغط عليه يفتح قائمة Edit/Move-Copy/Delete (مش pick)
            av_name = trim_name(av.get("name", "No Name"))
            name_float = FloatLayout(size_hint_y=None, height=32)
            lbl_name = Label(text=av_name, size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            name_menu_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                   background_color=(0, 0, 0, 0))
            name_menu_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))
            name_float.add_widget(lbl_name)
            name_float.add_widget(name_menu_btn)
            cell.add_widget(name_float)

            self._av_grid.add_widget(cell)

        if end < len(avatars):
            Clock.schedule_once(lambda dt, s=end: self._load_av_batch(s), 0)
        else:
            # القائمة خلصت تحميل - نحفظ أي thumbnails جديدة اتبنت دفعة واحدة
            Clock.schedule_once(lambda dt: flush_avatar_thumbnails_if_dirty(), 0)

    def _pick(self, idx):
        self.on_select(AVATARS[idx])
        self.dismiss()

    def _open_move_copy(self, idx):
        item = AVATARS[idx]

        def _remove():
            AVATARS.pop(idx)
            save_avatars()

        open_move_copy_popup(item, ("avatar", None), _remove, self._refresh_grid)

    def _drag_start(self, idx, touch):
        self._drag_idx = idx
        self._drag_ref = touch.pos

    def _drag_move(self, touch):
        if self._drag_idx is None:
            return
        grid = getattr(self, "_av_grid", None)
        if not grid or grid.width <= 0:
            return
        cols = 5
        cell_h = 146
        cell_w = grid.width / cols
        dx = touch.pos[0] - self._drag_ref[0]
        dy = self._drag_ref[1] - touch.pos[1]
        idx = self._drag_idx
        moved = False
        if dx > cell_w * 0.6 and idx < len(AVATARS) - 1:
            AVATARS[idx], AVATARS[idx + 1] = AVATARS[idx + 1], AVATARS[idx]
            self._drag_idx += 1
            moved = True
        elif dx < -cell_w * 0.6 and idx > 0:
            AVATARS[idx], AVATARS[idx - 1] = AVATARS[idx - 1], AVATARS[idx]
            self._drag_idx -= 1
            moved = True
        elif dy > cell_h * 0.6 and idx + cols < len(AVATARS):
            AVATARS[idx], AVATARS[idx + cols] = AVATARS[idx + cols], AVATARS[idx]
            self._drag_idx += cols
            moved = True
        elif dy < -cell_h * 0.6 and idx - cols >= 0:
            AVATARS[idx], AVATARS[idx - cols] = AVATARS[idx - cols], AVATARS[idx]
            self._drag_idx -= cols
            moved = True
        if moved:
            self._drag_ref = touch.pos
            save_avatars()
            self._refresh_grid()

    def _drag_end(self, touch):
        self._drag_idx = None
        self._drag_ref = None

    def _open_item_menu(self, idx):
        """زرار ⋮ العلوي: Edit Avatar / Move to Scroll / Delete Avatar.
        الترتيب بقى بالسحب (long-press + drag) بدل زراير Up/Down."""
        av = AVATARS[idx]
        content = BoxLayout(orientation="vertical", spacing=6, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.2))

        edit_btn = Button(text="Edit Avatar", background_color=(0.2, 0.55, 0.85, 1))
        move_btn = Button(text="Copy to Scroll", background_color=(0.25, 0.65, 0.4, 1))
        mvcp_btn = Button(text="Move/Copy", background_color=(0.45, 0.35, 0.7, 1))
        del_btn  = Button(text="Delete Avatar", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(edit_btn)
        content.add_widget(move_btn)
        content.add_widget(mvcp_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.75, 0.6))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        move_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._move_to_scroll(idx)))
        mvcp_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._open_move_copy(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _toggle_arrange(self):
        self._arrange_mode = not self._arrange_mode
        self.arrange_btn.background_color = (0.25, 0.65, 0.4, 1) if self._arrange_mode else (0.5, 0.5, 0.5, 1)
        self._refresh_grid()

    def _move_to_scroll(self, idx):
        """ينسخ الأفاتار من قائمة Avatar لقائمة Scroll (بيفضل موجود في Avatar
        كمان). لو عنده لينك محفوظ بالفعل بيتحافظ عليه، ولو من غير لينك
        بيتضاف من غير لينك وتقدر تضيفه بعدين من جوه Scroll عن طريق Edit."""
        av = AVATARS[idx]

        def do_copy(instance):
            confirm_popup.dismiss()
            new_av = dict(av)
            new_av["link"] = new_av.get("link", "")
            new_av.pop("thumb_b64", None)
            new_av.pop("thumb_ext", None)
            SCROLL_AVATARS.append(new_av)
            save_scroll_avatars()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Copy "{av.get("name","")}" to Scroll?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Copy", background_color=(0.25, 0.65, 0.4, 1))
        no_btn  = Button(text="Cancel")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Copy", content=content, size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=do_copy)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()

    def _edit(self, idx):
        av = AVATARS[idx]

        def on_saved(new_name, new_b64, new_ext, new_path):
            # مسح الكاش (الأصلي + المصغّر) للأفاتار ده عشان يتحمّل بالصورة الجديدة
            old_key = av.get("path") or ("b64:" + av.get("b64", "")[:32])
            _AVATAR_TEXTURE_CACHE.pop(old_key, None)
            _AVATAR_TEXTURE_CACHE.pop("thumb:" + old_key, None)
            AVATARS[idx]["name"] = new_name
            if new_path:
                AVATARS[idx]["path"] = new_path
                AVATARS[idx]["ext"] = new_ext
                # الملف الأصلي محفوظ بالفعل على الديسك في new_path - مفيش داعي
                # نكرر نفس الصورة كاملة كـ base64 جوه avatars.json كمان (ده كان
                # سبب تضخم الملف وبطء تحميله). بنخزن b64 بس لو الحفظ كملف فشل.
                AVATARS[idx]["b64"] = "" if new_path else new_b64
                # الصورة اتغيرت - نمسح الـ thumbnail القديم عشان يتبني واحد جديد
                AVATARS[idx].pop("thumb_b64", None)
                AVATARS[idx].pop("thumb_ext", None)
            save_avatars()
            # لو نفس المسار موجود في أي قائمة Scroll (مش النشطة بس)، حدّث الاسم هناك كمان
            for lst in SCROLL_LISTS:
                for s in lst.get("avatars", []):
                    if s.get("path") == av.get("path"):
                        s["name"] = new_name
                        if new_path:
                            s["path"] = new_path
                            s["ext"] = new_ext
                            s["b64"] = "" if new_path else new_b64
                            s.pop("thumb_b64", None)
                            s.pop("thumb_ext", None)
            save_scroll_lists()
            self._refresh_grid()

        popup = EditAvatarPopup(av, on_saved=on_saved)
        popup.open()

    def _delete(self, idx):
        av = AVATARS[idx]
        def confirm_delete(instance):
            confirm_popup.dismiss()
            img_path = av.get("path", "")
            other_paths = _all_other_paths(exclude_avatars_idx=idx)
            if img_path and img_path not in other_paths and os.path.exists(img_path):
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

        change_img_btn = Button(text="Change Image (from device)", size_hint_y=0.13)
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
        picker = ImagePickerPopup(on_select=self._on_new_image_picked)
        picker.open()

    def _on_new_image_picked(self, img_path):
        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            with open(img_path, "rb") as _f:
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

        # ===== شريط علوي: اسم القائمة الحالية + التبديل بين القوائم + قائمة جديدة =====
        self.list_bar = BoxLayout(orientation="horizontal", size_hint_y=None, height=44, spacing=4, padding=(4, 0))
        self.list_btn = Button(text="List", halign="center", valign="middle")
        self.list_btn.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0] - 10, None)))
        self.list_btn.bind(on_press=lambda x: self._open_switch_list())
        new_list_btn = Button(text="+ List", size_hint_x=None, width=80)
        new_list_btn.bind(on_press=lambda x: self._open_new_list())
        list_opts_btn = Button(text="⋮", size_hint_x=None, width=44)
        list_opts_btn.bind(on_press=lambda x: self._open_list_options())
        self.list_bar.add_widget(self.list_btn)
        self.list_bar.add_widget(new_list_btn)
        self.list_bar.add_widget(list_opts_btn)
        self.root_layout.add_widget(self.list_bar)

        self.scroll = ScrollView(size_hint_y=1)
        self.grid_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self.grid_container.bind(minimum_height=self.grid_container.setter("height"))
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        Clock.schedule_once(lambda dt: self._refresh_grid(), 0)

    def _current_list_name(self):
        sync_scroll_avatars_ref()
        return SCROLL_LISTS[SCROLL_ACTIVE_LIST].get("name", "List")

    def _open_switch_list(self):
        """يعرض كل القوائم الموجودة كأزرار — الضغط على واحدة يفتحها."""
        global SCROLL_ACTIVE_LIST
        content = BoxLayout(orientation="vertical", spacing=8, padding=12, size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        inner_scroll = ScrollView(size_hint=(1, 1))
        inner_scroll.add_widget(content)

        menu_popup = Popup(title="Switch List", content=inner_scroll, size_hint=(0.8, 0.7))

        for i, lst in enumerate(SCROLL_LISTS):
            label = lst.get("name", "List") + (f"  ({len(lst.get('avatars', []))})")
            btn = Button(text=label, size_hint_y=None, height=48,
                        background_color=(0.2, 0.55, 0.85, 1) if i == SCROLL_ACTIVE_LIST else (0.35, 0.35, 0.35, 1))

            def do_switch(x, i=i):
                global SCROLL_ACTIVE_LIST
                SCROLL_ACTIVE_LIST = i
                sync_scroll_avatars_ref()
                save_scroll_lists()
                menu_popup.dismiss()
                self._refresh_grid()

            btn.bind(on_press=do_switch)
            content.add_widget(btn)

        cancel_btn = Button(text="Cancel", size_hint_y=None, height=44)
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        content.add_widget(cancel_btn)
        menu_popup.open()

    def _open_new_list(self):
        """يفتح popup لإدخال اسم قائمة جديدة (فيه اسم افتراضي List N) وينشئها."""
        default_name = f"List {len(SCROLL_LISTS) + 1}"
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="New list name:", font_size="15sp", size_hint_y=0.3))
        name_input = TextInput(text=default_name, multiline=False, size_hint_y=0.3)
        content.add_widget(name_input)
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        create_btn = Button(text="Create", background_color=(0.25, 0.65, 0.4, 1))
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(create_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)
        popup = Popup(title="New List", content=content, size_hint=(0.8, 0.4))

        def do_create(x):
            global SCROLL_ACTIVE_LIST
            name = (name_input.text or "").strip() or default_name
            SCROLL_LISTS.append({"name": name, "avatars": []})
            SCROLL_ACTIVE_LIST = len(SCROLL_LISTS) - 1
            sync_scroll_avatars_ref()
            save_scroll_lists()
            popup.dismiss()
            self._refresh_grid()

        create_btn.bind(on_press=do_create)
        cancel_btn.bind(on_press=lambda x: popup.dismiss())
        popup.open()

    def _open_list_options(self):
        """قائمة Rename / Delete للقائمة النشطة حاليًا."""
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        content.add_widget(Label(text=trim_name(self._current_list_name(), max_len=24), font_size="14sp", size_hint_y=0.3))

        rename_btn = Button(text="Rename List", background_color=(0.2, 0.55, 0.85, 1))
        del_btn = Button(text="Delete List", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")
        content.add_widget(rename_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="List Options", content=content, size_hint=(0.7, 0.45))
        rename_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._rename_list()))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete_list()))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _rename_list(self):
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="List name:", font_size="15sp", size_hint_y=0.3))
        name_input = TextInput(text=self._current_list_name(), multiline=False, size_hint_y=0.3)
        content.add_widget(name_input)
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        save_btn = Button(text="Save", background_color=(0.25, 0.65, 0.4, 1))
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)
        popup = Popup(title="Rename List", content=content, size_hint=(0.8, 0.4))

        def do_save(x):
            new_name = (name_input.text or "").strip()
            if new_name:
                SCROLL_LISTS[SCROLL_ACTIVE_LIST]["name"] = new_name
                save_scroll_lists()
                self._refresh_grid()
            popup.dismiss()

        save_btn.bind(on_press=do_save)
        cancel_btn.bind(on_press=lambda x: popup.dismiss())
        popup.open()

    def _delete_list(self):
        if len(SCROLL_LISTS) <= 1:
            content = BoxLayout(orientation="vertical", spacing=10, padding=12)
            content.add_widget(Label(text="You can't delete the only remaining list.", font_size="14sp"))
            ok_btn = Button(text="OK", size_hint_y=None, height=44)
            content.add_widget(ok_btn)
            info_popup = Popup(title="Not Allowed", content=content, size_hint=(0.75, 0.3))
            ok_btn.bind(on_press=lambda x: info_popup.dismiss())
            info_popup.open()
            return

        name = self._current_list_name()

        def confirm_delete(instance):
            global SCROLL_ACTIVE_LIST
            confirm_popup.dismiss()
            SCROLL_LISTS.pop(SCROLL_ACTIVE_LIST)
            if SCROLL_ACTIVE_LIST >= len(SCROLL_LISTS):
                SCROLL_ACTIVE_LIST = len(SCROLL_LISTS) - 1
            sync_scroll_avatars_ref()
            save_scroll_lists()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Delete list "{name}" and all its avatars?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        no_btn = Button(text="Cancel")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Delete", content=content, size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=confirm_delete)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()

    def _refresh_grid(self):
        sync_scroll_avatars_ref()
        self.title = "Scroll — Tap image to open link"
        self.list_btn.text = self._current_list_name() + "  ▾"

        self.grid_container.clear_widgets()
        if not SCROLL_AVATARS:
            self.grid_container.add_widget(
                Label(text="No linked avatars yet.", size_hint_y=None, height=60)
            )
            return

        from kivy.uix.floatlayout import FloatLayout
        self._sc_all = list(SCROLL_AVATARS)
        self._sc_grid = GridLayout(cols=5, size_hint_y=None, spacing=4, padding=4)
        self._sc_grid.bind(minimum_height=self._sc_grid.setter("height"))
        self.grid_container.add_widget(self._sc_grid)
        self._load_sc_batch(0)

    def _load_sc_batch(self, start, batch=8):
        """يحمّل batch من الأفاتارات ثم يجدول الـ batch التالية — الـ popup يظهر فوراً"""
        from kivy.uix.floatlayout import FloatLayout
        avatars = self._sc_all
        end = min(start + batch, len(avatars))

        for idx in range(start, end):
            av = avatars[idx]
            link = av.get("link", "")
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=120)

            texture = _load_avatar_texture(av)
            if texture:
                img_widget = Image(texture=texture, size_hint=(1, 1))
            else:
                img_widget = Label(text="?", size_hint=(1, 1))

            float_cell = FloatLayout(size_hint_y=None, height=88)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, lnk=link: self._open_link(lnk))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            cell.add_widget(float_cell)

            # اسم الأفاتار — الضغط عليه يفتح قائمة Edit/Delete
            av_name = trim_name(av.get("name", "No Name"))
            name_float = FloatLayout(size_hint_y=None, height=32)
            lbl_name = Label(text=av_name, size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            name_menu_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                   background_color=(0, 0, 0, 0))
            name_menu_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))
            name_float.add_widget(lbl_name)
            name_float.add_widget(name_menu_btn)
            cell.add_widget(name_float)

            self._sc_grid.add_widget(cell)

        if end < len(avatars):
            Clock.schedule_once(lambda dt, s=end: self._load_sc_batch(s), 0)
        else:
            Clock.schedule_once(lambda dt: flush_avatar_thumbnails_if_dirty(), 0)

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
        """زرار ⋮ العلوي: ترتيب (Up/Down) + Move to List + Edit Scroll + Delete Scroll."""
        av = SCROLL_AVATARS[idx]
        content = BoxLayout(orientation="vertical", spacing=6, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.22))

        order_row = BoxLayout(orientation="horizontal", spacing=6, size_hint_y=0.16)
        up_btn = Button(text="▲ Up", background_color=(0.35, 0.35, 0.35, 1))
        down_btn = Button(text="▼ Down", background_color=(0.35, 0.35, 0.35, 1))
        order_row.add_widget(up_btn)
        order_row.add_widget(down_btn)
        content.add_widget(order_row)

        move_btn = Button(text="Move to List...", background_color=(0.45, 0.35, 0.75, 1))
        edit_btn = Button(text="Edit Scroll", background_color=(0.2, 0.55, 0.85, 1))
        del_btn  = Button(text="Delete Scroll", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(move_btn)
        content.add_widget(edit_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.75, 0.62))
        up_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._reorder(idx, -1)))
        down_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._reorder(idx, 1)))
        move_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._open_move_to_list(idx)))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _reorder(self, idx, direction):
        """يبدّل مكان الأفاتار مع اللي جنبه (فوق لو direction=-1، تحت لو +1)."""
        new_idx = idx + direction
        if 0 <= new_idx < len(SCROLL_AVATARS):
            SCROLL_AVATARS[idx], SCROLL_AVATARS[new_idx] = SCROLL_AVATARS[new_idx], SCROLL_AVATARS[idx]
            save_scroll_avatars()
            self._refresh_grid()

    def _open_move_to_list(self, idx):
        """ينقل الأفاتار لقائمة Scroll تانية (بيتشال من القائمة الحالية)."""
        av = SCROLL_AVATARS[idx]
        other_lists = [i for i in range(len(SCROLL_LISTS)) if i != SCROLL_ACTIVE_LIST]
        if not other_lists:
            content = BoxLayout(orientation="vertical", spacing=10, padding=12)
            content.add_widget(Label(text="No other lists yet — create one first.", font_size="14sp"))
            ok_btn = Button(text="OK", size_hint_y=None, height=44)
            content.add_widget(ok_btn)
            info_popup = Popup(title="Move to List", content=content, size_hint=(0.75, 0.3))
            ok_btn.bind(on_press=lambda x: info_popup.dismiss())
            info_popup.open()
            return

        content = BoxLayout(orientation="vertical", spacing=8, padding=12, size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        inner_scroll = ScrollView(size_hint=(1, 1))
        inner_scroll.add_widget(content)
        menu_popup = Popup(title=f'Move "{trim_name(av.get("name",""), max_len=18)}" to...', content=inner_scroll, size_hint=(0.8, 0.7))

        for i in other_lists:
            target_name = SCROLL_LISTS[i].get("name", "List")
            btn = Button(text=target_name, size_hint_y=None, height=48, background_color=(0.35, 0.35, 0.35, 1))

            def do_move(x, i=i):
                moved = SCROLL_AVATARS.pop(idx)
                SCROLL_LISTS[i]["avatars"].append(moved)
                save_scroll_lists()
                menu_popup.dismiss()
                self._refresh_grid()

            btn.bind(on_press=do_move)
            content.add_widget(btn)

        cancel_btn = Button(text="Cancel", size_hint_y=None, height=44)
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        content.add_widget(cancel_btn)
        menu_popup.open()

    def _edit(self, idx):
        av = SCROLL_AVATARS[idx]

        def on_saved(new_name, new_b64, new_ext, new_path, new_link):
            old_key = av.get("path") or ("b64:" + av.get("b64", "")[:32])
            _AVATAR_TEXTURE_CACHE.pop(old_key, None)
            _AVATAR_TEXTURE_CACHE.pop("thumb:" + old_key, None)
            SCROLL_AVATARS[idx]["name"] = new_name
            SCROLL_AVATARS[idx]["link"] = new_link
            if new_path:
                SCROLL_AVATARS[idx]["path"] = new_path
                SCROLL_AVATARS[idx]["ext"] = new_ext
                SCROLL_AVATARS[idx]["b64"] = "" if new_path else new_b64
                SCROLL_AVATARS[idx].pop("thumb_b64", None)
                SCROLL_AVATARS[idx].pop("thumb_ext", None)
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

        select_btn = Button(text="Select Image", background_color=(0.2, 0.6, 0.2, 1))
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

        select_btn = Button(text="Select File", background_color=(0.2, 0.6, 0.2, 1))
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
        content.add_widget(Label(text="File name:", font_size="13sp", size_hint_y=None, height=22))
        self.name_input = TextInput(
            text=self.result.get("filename_base", ""),
            multiline=False, size_hint_y=None, height=40
        )
        content.add_widget(self.name_input)

        content.add_widget(Label(text="Choose save format:", font_size="14sp"))
        btn_row = BoxLayout(size_hint_y=None, height=46, spacing=8)
        md_btn = Button(text="Markdown (.md)")
        html_btn = Button(text="HTML (.html)")
        both_btn = Button(text="Both")
        btn_row.add_widget(md_btn)
        btn_row.add_widget(html_btn)
        btn_row.add_widget(both_btn)
        content.add_widget(btn_row)
        cancel_btn = Button(text="Cancel", size_hint_y=None, height=40)
        content.add_widget(cancel_btn)

        choice_popup = Popup(title="Save Article", content=content, size_hint=(0.85, 0.42))
        md_btn.bind(on_press=lambda i: self._save_as(choice_popup, "md"))
        html_btn.bind(on_press=lambda i: self._save_as(choice_popup, "html"))
        both_btn.bind(on_press=lambda i: self._save_as(choice_popup, "both"))
        cancel_btn.bind(on_press=lambda i: choice_popup.dismiss())
        choice_popup.open()

    def _save_as(self, choice_popup, fmt):
        custom_name = self.name_input.text.strip() if hasattr(self, "name_input") else ""
        choice_popup.dismiss()
        res = self.result
        if not res:
            return
        if custom_name:
            res["filename_base"] = custom_name

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
        save_dir = os.path.join(save_dir, "touch clip")
        os.makedirs(save_dir, exist_ok=True)

        base_name = res["filename_base"]

        def unique_path(ext):
            p = os.path.join(save_dir, f"{base_name}.{ext}")
            counter = 1
            while os.path.exists(p):
                p = os.path.join(save_dir, f"{base_name}_{counter}.{ext}")
                counter += 1
            return p

        def md_text():
            return re.sub(
                r'\[\[chart:(.+?)\|(.*?)\]\]',
                lambda m: (f"![chart]({m.group(2)})\n\n" if m.group(2) else "")
                          + f"📊 Interactive chart: {m.group(1)}",
                res["markdown"]
            )

        def html_text():
            html_out = article_to_html(res)
            # ضغط بسيط: إزالة السطور الفارغة المتكررة والمسافات الزائدة
            html_out = re.sub(r'\n\s*\n\s*\n', '\n\n', html_out)
            html_out = re.sub(r'[ \t]+\n', '\n', html_out)
            return html_out

        saved_paths = []
        try:
            if fmt in ("md", "both"):
                md_path = unique_path("md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_text())
                saved_paths.append(md_path)

            if fmt in ("html", "both"):
                html_path = unique_path("html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_text())
                saved_paths.append(html_path)
        except Exception as e:
            self.preview.text = "❌ Save failed: " + str(e)
            return

        self.preview.markup = False
        self.preview.text = "✓ Saved to:\n" + "\n".join(saved_paths)
        if self.on_saved:
            self.on_saved(saved_paths[-1])


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

        create_btn = Button(text="Create Task", size_hint_y=None, height=44,
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

            del_btn = Button(text="", size_hint_x=None, width=40,
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
        task = TASKS[idx]

        def confirm_delete(instance):
            confirm_popup.dismiss()
            TASKS.pop(idx)
            save_tasks(TASKS)
            self._refresh()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Delete task "{task.get("name","")}"?', font_size="15sp"))
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        yes_btn = Button(text="Yes", background_color=(0.85, 0.2, 0.2, 1))
        no_btn  = Button(text="No")
        btn_row.add_widget(yes_btn)
        btn_row.add_widget(no_btn)
        content.add_widget(btn_row)
        confirm_popup = Popup(title="Confirm Delete", content=content, size_hint=(0.75, 0.3))
        yes_btn.bind(on_press=confirm_delete)
        no_btn.bind(on_press=lambda x: confirm_popup.dismiss())
        confirm_popup.open()


class TaskDetailPopup(Popup):
    """نافذة تفاصيل مهمة واحدة: شبكة أفاتارات (اسم + صورة + لينك).
    - الضغط على الصورة: يفتح لينك المصمم.
    - الضغط على الاسم: قائمة (Edit / Delete / Notes / Reset Counter).
    - عداد فوق كل عنصر: الضغط عليه يزيد ١، ٢، ٣... ويُصفّر من قائمة الاسم."""
    def __init__(self, task_idx, on_change=None, **kwargs):
        super().__init__(**kwargs)
        self.task_idx = task_idx
        self.on_change = on_change
        self._drag_idx = None
        self._drag_ref = None
        self._grid = None
        self._arrange_mode = False
        task = TASKS[self.task_idx]
        self.title = ""
        self.separator_height = 0
        self.size_hint = (0.94, 0.9)

        self.root_layout = BoxLayout(orientation="vertical")

        top_row = BoxLayout(size_hint_y=None, height=46, spacing=6, padding=(8, 2))
        title_lbl = Label(text=f"📋 {task.get('name','Task')}", font_size="15sp", bold=True,
                          halign="left", valign="middle", shorten=True, shorten_from="right")
        title_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        add_btn = Button(text="Add Avatar", font_size="12sp", size_hint_x=None, width=110,
                         background_color=(0.15, 0.6, 0.35, 1))
        add_btn.bind(on_press=self._do_add_item)
        self.arrange_btn = Button(text="⇕", font_size="18sp", size_hint=(None, None),
                                   size=(44, 40), background_color=(0.5, 0.5, 0.5, 1))
        self.arrange_btn.bind(on_press=lambda x: self._toggle_arrange())
        top_row.add_widget(title_lbl)
        top_row.add_widget(add_btn)
        top_row.add_widget(self.arrange_btn)
        self.root_layout.add_widget(top_row)

        self.scroll = ScrollView()
        self.grid_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self.grid_container.bind(minimum_height=self.grid_container.setter("height"))
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        Clock.schedule_once(lambda dt: self._refresh_grid(), 0)

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
        self._grid = grid

        for idx, av in enumerate(items):
            link = av.get("link", "")
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=206)

            try:
                texture = _load_avatar_texture(av, thumb=True)
                if texture:
                    img_widget = Image(texture=texture, size_hint=(1, 1))
                else:
                    img_widget = Label(text="?", size_hint=(1, 1))
            except Exception:
                img_widget = Label(text="?", size_hint=(1, 1))

            float_cell = FloatLayout(size_hint_y=None, height=130)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = DragCell(idx, on_long_press=self._drag_start, on_drag_move=self._drag_move,
                              on_drag_end=self._drag_end, arrange_mode=self._arrange_mode,
                              size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                              background_color=(0, 0, 0, 0))
            img_btn.bind(on_press=lambda x, lnk=link: self._open_link(lnk))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            cell.add_widget(float_cell)

            # اسم الأفاتار تحت الصورة (ممكن يكون فاضي لو الأفاتار اتسجل
            # بدون اسم) - الضغط عليه دايمًا يفتح قائمة Edit / Note / Move-Copy / Delete
            av_name = trim_name(av.get("name") or "")
            lbl_name = Label(text=av_name, size_hint_y=None, height=44,
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            name_float = FloatLayout(size_hint_y=None, height=44)
            lbl_name.pos_hint = {"x": 0, "y": 0}
            name_sel_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                  background_color=(0, 0, 0, 0))
            name_sel_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))
            name_float.add_widget(lbl_name)
            name_float.add_widget(name_sel_btn)
            cell.add_widget(name_float)

            grid.add_widget(cell)

        self.grid_container.add_widget(grid)
        flush_avatar_thumbnails_if_dirty()

    def _toggle_arrange(self):
        self._arrange_mode = not self._arrange_mode
        self.arrange_btn.background_color = (0.25, 0.65, 0.4, 1) if self._arrange_mode else (0.5, 0.5, 0.5, 1)
        self._refresh_grid()

    def _open_move_copy(self, idx):
        item = self._items()[idx]

        def _remove():
            self._items().pop(idx)
            self._persist()

        open_move_copy_popup(item, ("task", self.task_idx), _remove, self._refresh_grid)

    def _drag_start(self, idx, touch):
        self._drag_idx = idx
        self._drag_ref = touch.pos

    def _drag_move(self, touch):
        if self._drag_idx is None or not self._grid or self._grid.width <= 0:
            return
        items = self._items()
        cols = 4
        cell_h = 206
        cell_w = self._grid.width / cols
        dx = touch.pos[0] - self._drag_ref[0]
        dy = self._drag_ref[1] - touch.pos[1]
        idx = self._drag_idx
        moved = False
        if dx > cell_w * 0.6 and idx < len(items) - 1:
            items[idx], items[idx + 1] = items[idx + 1], items[idx]
            self._drag_idx += 1
            moved = True
        elif dx < -cell_w * 0.6 and idx > 0:
            items[idx], items[idx - 1] = items[idx - 1], items[idx]
            self._drag_idx -= 1
            moved = True
        elif dy > cell_h * 0.6 and idx + cols < len(items):
            items[idx], items[idx + cols] = items[idx + cols], items[idx]
            self._drag_idx += cols
            moved = True
        elif dy < -cell_h * 0.6 and idx - cols >= 0:
            items[idx], items[idx - cols] = items[idx - cols], items[idx]
            self._drag_idx -= cols
            moved = True
        if moved:
            self._drag_ref = touch.pos
            self._persist()
            self._refresh_grid()

    def _drag_end(self, touch):
        self._drag_idx = None
        self._drag_ref = None

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

        name_input = TextInput(hint_text="Name (optional)", multiline=False, size_hint_y=0.12)
        link_input = TextInput(hint_text="Link (optional)", multiline=False, size_hint_y=0.12)
        root.add_widget(name_input)
        root.add_widget(link_input)

        btn_row = BoxLayout(size_hint_y=0.16, spacing=6)
        ok_btn  = Button(text="Add", background_color=(0.15, 0.6, 0.35, 1))
        can_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(can_btn)
        root.add_widget(btn_row)

        add_popup = Popup(title="Add Avatar", content=root, size_hint=(0.82, 0.7))
        captured_ext = ext

        def _confirm(inst):
            name = name_input.text.strip()
            link = link_input.text.strip()
            try:
                img_path, saved_ext = save_avatar_image(b64_data, captured_ext, name or "avatar")
            except Exception:
                img_path, saved_ext = "", captured_ext
            # نبني الـ thumbnail دلوقتي وقت الإضافة - مش لازم ننتظر أول فتح للقائمة
            thumb_b64, thumb_ext = make_thumbnail_b64(base64.b64decode(b64_data), captured_ext)
            entry = {"name": name, "link": link, "path": img_path,
                     "ext": saved_ext, "b64": ("" if img_path else b64_data),
                     "thumb_b64": thumb_b64, "thumb_ext": thumb_ext,
                     "notes": "", "count": 0}
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

        note_text = av.get("notes", "").strip()
        if note_text:
            note_lbl = Label(text=note_text, font_size="11sp", color=(1, 0.85, 0.3, 1),
                             halign="center", valign="middle", size_hint_y=0.28)
            note_lbl.bind(size=note_lbl.setter("text_size"))
            content.add_widget(note_lbl)

        edit_btn   = Button(text="Edit", background_color=(0.2, 0.55, 0.85, 1))
        note_btn   = Button(text="Note", background_color=(0.55, 0.5, 0.15, 1))
        mvcp_btn   = Button(text="Move/Copy", background_color=(0.45, 0.35, 0.7, 1))
        del_btn    = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")

        content.add_widget(edit_btn)
        content.add_widget(note_btn)
        content.add_widget(mvcp_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.7, 0.6))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        note_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit_notes(idx)))
        mvcp_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._open_move_copy(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _edit(self, idx):
        av = self._items()[idx]

        def on_saved(new_name, new_b64, new_ext, new_path, new_link):
            old_key = av.get("path") or ("b64:" + av.get("b64", "")[:32])
            _AVATAR_TEXTURE_CACHE.pop(old_key, None)
            _AVATAR_TEXTURE_CACHE.pop("thumb:" + old_key, None)
            items = self._items()
            items[idx]["name"] = new_name
            items[idx]["link"] = new_link
            if new_path:
                items[idx]["path"] = new_path
                items[idx]["ext"] = new_ext
                items[idx]["b64"] = "" if new_path else new_b64
                items[idx].pop("thumb_b64", None)
                items[idx].pop("thumb_ext", None)
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
            self._refresh_grid()

        save_btn.bind(on_press=_save)
        cancel_btn.bind(on_press=lambda x: notes_popup.dismiss())
        notes_popup.open()

    def _view_note(self, idx):
        av = self._items()[idx]
        note_text = av.get("notes", "").strip()
        if not note_text:
            return
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        lbl = Label(text=note_text, halign="left", valign="top",
                    font_size="13sp", color=(1, 1, 1, 1))
        lbl.bind(size=lbl.setter("text_size"))
        content.add_widget(lbl)
        close_btn = Button(text="Close", size_hint_y=None, height=44)
        content.add_widget(close_btn)
        note_popup = Popup(title=trim_name(av.get("name", ""), max_len=24),
                           content=content, size_hint=(0.85, 0.55))
        close_btn.bind(on_press=lambda x: note_popup.dismiss())
        note_popup.open()

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
# NamedAvatarListsPopup + AvatarListDetailPopup
# نفس بنية Task بالظبط (قائمة قوائم -> تفاصيل قايمة واحدة)، بس شغالة
# على أي مصدر بيانات شكله [{"name":.., "avatars":[...]}] - مستخدمة
# حاليًا لكل من Scroll (show_link=True) و Avatar 2 (on_select=set_avatar).
# =========================
class NamedAvatarListsPopup(Popup):
    """شاشة قائمة القوائم: اسم + عدد + حذف لكل قايمة، وزرار Create List.
    الضغط على قايمة يفتح تفاصيلها في AvatarListDetailPopup."""
    def __init__(self, lists_ref, save_fn, title="Lists", on_select=None,
                 show_link=False, on_open_index=None, kind=None, **kwargs):
        super().__init__(**kwargs)
        self.lists_ref = lists_ref      # المرجع الفعلي (SCROLL_LISTS أو AVATAR2_LISTS) - بيتعدّل in place
        self.save_fn = save_fn
        self.on_select = on_select      # لو موجودة: اختيار أفاتار من جوه بيقفل الشاشتين ويرجعها هنا
        self.show_link = show_link
        self.on_open_index = on_open_index
        self.kind = kind                # "scroll" أو "avatar2" - يستخدم في Move/Copy
        self.title = title
        self.size_hint = (0.92, 0.88)

        self.root_layout = BoxLayout(orientation="vertical", spacing=6, padding=8)

        create_btn = Button(text="Create List", size_hint_y=None, height=44,
                            background_color=(0.2, 0.6, 0.3, 1))
        create_btn.bind(on_press=self._show_create_dialog)
        self.root_layout.add_widget(create_btn)

        self.scroll = ScrollView()
        self.lists_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=4)
        self.lists_container.bind(minimum_height=self.lists_container.setter("height"))
        self.scroll.add_widget(self.lists_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        self._refresh()

    def _refresh(self):
        if not self.lists_ref:
            self.lists_ref.append({"name": "List 1", "avatars": []})
            self.save_fn()
        self.lists_container.clear_widgets()

        for idx, lst in enumerate(self.lists_ref):
            row = BoxLayout(size_hint_y=None, height=50, spacing=6)

            open_btn = Button(text=lst.get("name", ""), halign="left", valign="middle",
                              font_size="13sp")
            open_btn.bind(on_press=lambda x, i=idx: self._open_list(i))

            count_lbl = Label(text=str(len(lst.get("avatars", []))), size_hint_x=None,
                              width=34, font_size="12sp", color=(0.7, 0.7, 0.7, 1))

            del_btn = Button(text="X", size_hint_x=None, width=40,
                             background_color=(0.7, 0.2, 0.2, 1))
            del_btn.bind(on_press=lambda x, i=idx: self._delete_list(i))

            row.add_widget(open_btn)
            row.add_widget(count_lbl)
            row.add_widget(del_btn)
            self.lists_container.add_widget(row)

    def _show_create_dialog(self, x):
        default_name = f"List {len(self.lists_ref) + 1}"
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="List name:", size_hint_y=0.3))
        name_input = TextInput(text=default_name, multiline=False, size_hint_y=0.35)
        content.add_widget(name_input)

        btn_row = BoxLayout(size_hint_y=0.3, spacing=8)
        ok_btn  = Button(text="Create", background_color=(0.2, 0.65, 0.3, 1))
        can_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(can_btn)
        content.add_widget(btn_row)

        dlg = Popup(title="Create List", content=content, size_hint=(0.8, 0.36))

        def _create(inst):
            name = (name_input.text or "").strip() or default_name
            self.lists_ref.append({"name": name, "avatars": []})
            self.save_fn()
            new_idx = len(self.lists_ref) - 1
            dlg.dismiss()
            self._refresh()
            self._open_list(new_idx)

        ok_btn.bind(on_press=_create)
        can_btn.bind(on_press=lambda i: dlg.dismiss())
        dlg.open()

    def _open_list(self, idx):
        if self.on_open_index:
            self.on_open_index(idx)

        on_select = None
        if self.on_select:
            def on_select(av):
                self.dismiss()
                self.on_select(av)

        detail = AvatarListDetailPopup(self.lists_ref[idx], self.save_fn,
                                       on_change=self._refresh,
                                       on_select=on_select,
                                       show_link=self.show_link,
                                       kind=self.kind, list_idx=idx)
        detail.open()

    def _delete_list(self, idx):
        if len(self.lists_ref) <= 1:
            content = BoxLayout(orientation="vertical", spacing=10, padding=12)
            content.add_widget(Label(text="You can't delete the only remaining list.", font_size="14sp"))
            ok_btn = Button(text="OK", size_hint_y=None, height=44)
            content.add_widget(ok_btn)
            info_popup = Popup(title="Not Allowed", content=content, size_hint=(0.75, 0.3))
            ok_btn.bind(on_press=lambda x: info_popup.dismiss())
            info_popup.open()
            return

        name = self.lists_ref[idx].get("name", "List")

        def confirm_delete(instance):
            confirm_popup.dismiss()
            self.lists_ref.pop(idx)
            self.save_fn()
            self._refresh()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Delete list "{name}" and all its avatars?', font_size="15sp"))
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


class AvatarListDetailPopup(Popup):
    """تفاصيل قائمة واحدة: شبكة أفاتارات + زرار Add Avatar.
    - لو on_select موجودة: الضغط على الصورة يختار الأفاتار (وضع اختيار
      للبوست - ده استخدام Avatar 2).
    - لو مش موجودة وshow_link=True: الضغط على الصورة يفتح اللينك
      (ده استخدام Scroll)."""
    def __init__(self, lst, save_fn, on_change=None, on_select=None, show_link=False,
                 kind=None, list_idx=None, **kwargs):
        super().__init__(**kwargs)
        self.lst = lst
        self.save_fn = save_fn
        self.on_change = on_change
        self.on_select = on_select
        self.show_link = show_link
        self.kind = kind          # "scroll" أو "avatar2" - يستخدم في Move/Copy
        self.list_idx = list_idx
        self._drag_idx = None
        self._drag_ref = None
        self._grid = None
        self._arrange_mode = False
        self.title = ""
        self.separator_height = 0
        self.size_hint = (0.94, 0.9)

        self.root_layout = BoxLayout(orientation="vertical")

        top_row = BoxLayout(size_hint_y=None, height=46, spacing=6, padding=(8, 2))
        title_lbl = Label(text="📋 " + lst.get("name", "List"), font_size="15sp", bold=True,
                          halign="left", valign="middle", shorten=True, shorten_from="right")
        title_lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        add_btn = Button(text="Add Avatar", font_size="12sp", size_hint_x=None, width=110,
                         background_color=(0.15, 0.6, 0.35, 1))
        add_btn.bind(on_press=self._do_add_item)
        self.arrange_btn = Button(text="⇕", font_size="18sp", size_hint=(None, None),
                                   size=(44, 40), background_color=(0.5, 0.5, 0.5, 1))
        self.arrange_btn.bind(on_press=lambda x: self._toggle_arrange())
        top_row.add_widget(title_lbl)
        top_row.add_widget(add_btn)
        top_row.add_widget(self.arrange_btn)
        self.root_layout.add_widget(top_row)

        self.scroll = ScrollView()
        self.grid_container = BoxLayout(orientation="vertical", size_hint_y=None)
        self.grid_container.bind(minimum_height=self.grid_container.setter("height"))
        self.scroll.add_widget(self.grid_container)
        self.root_layout.add_widget(self.scroll)

        close_btn = Button(text="Close", size_hint_y=None, height=44)
        close_btn.bind(on_press=lambda x: self.dismiss())
        self.root_layout.add_widget(close_btn)

        self.content = self.root_layout
        Clock.schedule_once(lambda dt: self._refresh_grid(), 0)

    def _items(self):
        return self.lst.setdefault("avatars", [])

    def _persist(self):
        self.save_fn()
        if self.on_change:
            self.on_change()

    def _refresh_grid(self):
        from kivy.uix.floatlayout import FloatLayout

        self.grid_container.clear_widgets()
        items = self._items()
        if not items:
            self.grid_container.add_widget(
                Label(text="No avatars yet.\nPress 'Add Avatar' to add one.")
            )
            return

        grid = GridLayout(cols=4, size_hint_y=None, spacing=4, padding=4)
        grid.bind(minimum_height=grid.setter("height"))
        self._grid = grid

        for idx, av in enumerate(items):
            link = av.get("link", "")
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=206)

            try:
                texture = _load_avatar_texture(av, thumb=True)
                img_widget = Image(texture=texture, size_hint=(1, 1)) if texture else Label(text="?", size_hint=(1, 1))
            except Exception:
                img_widget = Label(text="?", size_hint=(1, 1))

            float_cell = FloatLayout(size_hint_y=None, height=130)
            img_widget.pos_hint = {"x": 0, "y": 0}

            img_btn = DragCell(idx, on_long_press=self._drag_start, on_drag_move=self._drag_move,
                              on_drag_end=self._drag_end, arrange_mode=self._arrange_mode,
                              size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                              background_color=(0, 0, 0, 0))
            if self.on_select:
                img_btn.bind(on_press=lambda x, i=idx: self._pick(i))
            elif self.show_link:
                img_btn.bind(on_press=lambda x, lnk=link: self._open_link(lnk))

            float_cell.add_widget(img_widget)
            float_cell.add_widget(img_btn)
            cell.add_widget(float_cell)

            av_name = trim_name(av.get("name") or "")
            lbl_name = Label(text=av_name, size_hint_y=None, height=44,
                             font_size="10sp", halign="center", valign="middle",
                             shorten=True, shorten_from="right")
            lbl_name.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            name_float = FloatLayout(size_hint_y=None, height=44)
            lbl_name.pos_hint = {"x": 0, "y": 0}
            name_sel_btn = Button(size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
                                  background_color=(0, 0, 0, 0))
            name_sel_btn.bind(on_press=lambda x, i=idx: self._open_item_menu(i))
            name_float.add_widget(lbl_name)
            name_float.add_widget(name_sel_btn)
            cell.add_widget(name_float)

            grid.add_widget(cell)

        self.grid_container.add_widget(grid)
        flush_avatar_thumbnails_if_dirty()

    def _pick(self, idx):
        av = self._items()[idx]
        self.on_select(av)
        self.dismiss()

    def _toggle_arrange(self):
        self._arrange_mode = not self._arrange_mode
        self.arrange_btn.background_color = (0.25, 0.65, 0.4, 1) if self._arrange_mode else (0.5, 0.5, 0.5, 1)
        self._refresh_grid()

    def _open_move_copy(self, idx):
        item = self._items()[idx]

        def _remove():
            self._items().pop(idx)
            self._persist()

        exclude = (self.kind, self.list_idx) if self.kind else None
        open_move_copy_popup(item, exclude, _remove, self._refresh_grid)

    def _drag_start(self, idx, touch):
        self._drag_idx = idx
        self._drag_ref = touch.pos

    def _drag_move(self, touch):
        if self._drag_idx is None or not self._grid or self._grid.width <= 0:
            return
        items = self._items()
        cols = 4
        cell_h = 206
        cell_w = self._grid.width / cols
        dx = touch.pos[0] - self._drag_ref[0]
        dy = self._drag_ref[1] - touch.pos[1]
        idx = self._drag_idx
        moved = False
        if dx > cell_w * 0.6 and idx < len(items) - 1:
            items[idx], items[idx + 1] = items[idx + 1], items[idx]
            self._drag_idx += 1
            moved = True
        elif dx < -cell_w * 0.6 and idx > 0:
            items[idx], items[idx - 1] = items[idx - 1], items[idx]
            self._drag_idx -= 1
            moved = True
        elif dy > cell_h * 0.6 and idx + cols < len(items):
            items[idx], items[idx + cols] = items[idx + cols], items[idx]
            self._drag_idx += cols
            moved = True
        elif dy < -cell_h * 0.6 and idx - cols >= 0:
            items[idx], items[idx - cols] = items[idx - cols], items[idx]
            self._drag_idx -= cols
            moved = True
        if moved:
            self._drag_ref = touch.pos
            self._persist()
            self._refresh_grid()

    def _drag_end(self, touch):
        self._drag_idx = None
        self._drag_ref = None

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

    def _do_add_item(self, x):
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

        name_input = TextInput(hint_text="Name (optional)", multiline=False, size_hint_y=0.12)
        root.add_widget(name_input)
        link_input = None
        if self.show_link:
            link_input = TextInput(hint_text="Link (optional)", multiline=False, size_hint_y=0.12)
            root.add_widget(link_input)

        btn_row = BoxLayout(size_hint_y=0.16, spacing=6)
        ok_btn  = Button(text="Add", background_color=(0.15, 0.6, 0.35, 1))
        can_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(can_btn)
        root.add_widget(btn_row)

        add_popup = Popup(title="Add Avatar", content=root, size_hint=(0.82, 0.7))
        captured_ext = ext

        def _confirm(inst):
            name = name_input.text.strip()
            link = link_input.text.strip() if link_input else ""
            try:
                img_path, saved_ext = save_avatar_image(b64_data, captured_ext, name or "avatar")
            except Exception:
                img_path, saved_ext = "", captured_ext
            thumb_b64, thumb_ext = make_thumbnail_b64(base64.b64decode(b64_data), captured_ext)
            entry = {"name": name, "path": img_path,
                     "ext": saved_ext, "b64": ("" if img_path else b64_data),
                     "thumb_b64": thumb_b64, "thumb_ext": thumb_ext, "notes": ""}
            if self.show_link:
                entry["link"] = link
            self._items().append(entry)
            self._persist()
            add_popup.dismiss()
            self._refresh_grid()

        ok_btn.bind(on_press=_confirm)
        can_btn.bind(on_press=lambda i: add_popup.dismiss())
        add_popup.open()

    def _open_item_menu(self, idx):
        av = self._items()[idx]
        content = BoxLayout(orientation="vertical", spacing=6, padding=12)
        content.add_widget(Label(text=trim_name(av.get("name", ""), max_len=24), font_size="14sp", size_hint_y=0.2))

        edit_btn = Button(text="Edit", background_color=(0.2, 0.55, 0.85, 1))
        mvcp_btn = Button(text="Move/Copy", background_color=(0.45, 0.35, 0.7, 1))
        del_btn  = Button(text="Delete", background_color=(0.85, 0.2, 0.2, 1))
        cancel_btn = Button(text="Cancel")
        content.add_widget(edit_btn)
        content.add_widget(mvcp_btn)
        content.add_widget(del_btn)
        content.add_widget(cancel_btn)

        menu_popup = Popup(title="Options", content=content, size_hint=(0.75, 0.55))
        edit_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._edit(idx)))
        mvcp_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._open_move_copy(idx)))
        del_btn.bind(on_press=lambda x: (menu_popup.dismiss(), self._delete(idx)))
        cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
        menu_popup.open()

    def _edit(self, idx):
        av = self._items()[idx]

        def on_saved(new_name, new_b64, new_ext, new_path):
            self._apply_edit(idx, av, new_name, new_b64, new_ext, new_path, av.get("link", ""))

        def on_saved_with_link(new_name, new_b64, new_ext, new_path, new_link):
            self._apply_edit(idx, av, new_name, new_b64, new_ext, new_path, new_link)

        popup = EditAvatarPopup(av, on_saved=on_saved, on_saved_with_link=on_saved_with_link,
                                show_link=self.show_link)
        popup.open()

    def _apply_edit(self, idx, av, new_name, new_b64, new_ext, new_path, new_link):
        old_key = av.get("path") or ("b64:" + av.get("b64", "")[:32])
        _AVATAR_TEXTURE_CACHE.pop(old_key, None)
        _AVATAR_TEXTURE_CACHE.pop("thumb:" + old_key, None)
        items = self._items()
        items[idx]["name"] = new_name
        if self.show_link:
            items[idx]["link"] = new_link
        if new_path:
            items[idx]["path"] = new_path
            items[idx]["ext"] = new_ext
            items[idx]["b64"] = "" if new_path else new_b64
            items[idx].pop("thumb_b64", None)
            items[idx].pop("thumb_ext", None)
        self._persist()
        self._refresh_grid()

    def _delete(self, idx):
        av = self._items()[idx]

        def confirm_delete(instance):
            confirm_popup.dismiss()
            self._items().pop(idx)
            self._persist()
            self._refresh_grid()

        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text=f'Delete "{av.get("name","")}"?', font_size="15sp"))
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
# Move/Copy engine: نقل أو نسخ أفاتار واحد بين أي مكان في التطبيق
# (Avatar الأساسي / Avatar2 - أي قايمة / Scroll - أي قايمة / Task - أي مهمة)
# =========================
def _all_other_paths(exclude_avatars_idx=None):
    """كل مسارات الصور المستخدمة في أي مكان في التطبيق (لحماية ملف مشترك
    من الحذف لو لسه متستخدم في مكان تاني). exclude_avatars_idx بيستثني
    عنصر AVATARS اللي بنحذفه هو نفسه من الحساب."""
    paths = set()
    for i, av in enumerate(AVATARS):
        if i == exclude_avatars_idx:
            continue
        p = av.get("path", "")
        if p:
            paths.add(p)
    for lst in AVATAR2_LISTS:
        for av in lst.get("avatars", []):
            p = av.get("path", "")
            if p:
                paths.add(p)
    for lst in SCROLL_LISTS:
        for av in lst.get("avatars", []):
            p = av.get("path", "")
            if p:
                paths.add(p)
    for t in TASKS:
        for av in t.get("items", []):
            p = av.get("path", "")
            if p:
                paths.add(p)
    return paths


def _all_destinations(exclude=None):
    """يرجّع قائمة (label, kind, lists_ref, index) لكل الوجهات الممكنة،
    ما عدا exclude=(kind, index_or_None) بتاع المكان الحالي."""
    dests = []
    if exclude != ("avatar", None):
        dests.append(("Avatar", "avatar", None, None))
    for i, lst in enumerate(AVATAR2_LISTS):
        if exclude == ("avatar2", i):
            continue
        dests.append(("Avatar2 → " + lst.get("name", "List"), "avatar2", AVATAR2_LISTS, i))
    for i, lst in enumerate(SCROLL_LISTS):
        if exclude == ("scroll", i):
            continue
        dests.append(("Scroll → " + lst.get("name", "List"), "scroll", SCROLL_LISTS, i))
    for i, t in enumerate(TASKS):
        if exclude == ("task", i):
            continue
        dests.append(("Task → " + t.get("name", "Task"), "task", TASKS, i))
    return dests


def _dest_target_list(kind, lists_ref, idx):
    if kind == "avatar":
        return AVATARS
    if kind in ("avatar2", "scroll"):
        return lists_ref[idx].setdefault("avatars", [])
    if kind == "task":
        return lists_ref[idx].setdefault("items", [])
    return None


def _dest_save_fn(kind):
    if kind == "avatar":
        return save_avatars
    if kind == "avatar2":
        return save_avatar2_lists
    if kind == "scroll":
        return save_scroll_lists
    if kind == "task":
        return lambda: save_tasks(TASKS)
    return lambda: None


def _adapt_item_for_dest(item, kind):
    """بتنسخ العنصر وتضيف/تشيل الحقول اللي محتاجاها الوجهة (link لScroll/Task،
    notes/count لTask) من غير ما تفقد أي بيانات موجودة أصلاً."""
    new_item = dict(item)
    if kind in ("scroll", "task"):
        new_item.setdefault("link", "")
    if kind == "task":
        new_item.setdefault("notes", "")
        new_item.setdefault("count", 0)
    return new_item


def open_move_copy_popup(item, current_exclude, remove_from_source, on_done):
    """يفتح Move/Copy ثم قائمة الوجهات وينفّذ الاختيار.
    - item: dict الأفاتار الحالي
    - current_exclude: (kind, index_or_None) بتاع مكانه الحالي (يتشال من الوجهات)
    - remove_from_source: دالة من غير args بتشيله من مكانه (تتنادى بس لو Move)
    - on_done: دالة تتنادى بعد ما تخلص عشان الشاشة الحالية تعمل refresh"""
    content = BoxLayout(orientation="vertical", spacing=10, padding=12)
    content.add_widget(Label(text="Move or Copy \"" + trim_name(item.get("name", ""), max_len=20) + "\"?",
                             font_size="14sp", size_hint_y=0.3))
    btn_row = BoxLayout(size_hint_y=0.3, spacing=8)
    move_btn = Button(text="Move", background_color=(0.75, 0.45, 0.15, 1))
    copy_btn = Button(text="Copy", background_color=(0.2, 0.6, 0.5, 1))
    btn_row.add_widget(move_btn)
    btn_row.add_widget(copy_btn)
    content.add_widget(btn_row)
    cancel_btn = Button(text="Cancel", size_hint_y=None, height=44)
    content.add_widget(cancel_btn)
    action_popup = Popup(title="Move / Copy", content=content, size_hint=(0.78, 0.42))

    def choose(action):
        action_popup.dismiss()
        _open_destination_menu(item, current_exclude, action, remove_from_source, on_done)

    move_btn.bind(on_press=lambda x: choose("move"))
    copy_btn.bind(on_press=lambda x: choose("copy"))
    cancel_btn.bind(on_press=lambda x: action_popup.dismiss())
    action_popup.open()


def _open_destination_menu(item, current_exclude, action, remove_from_source, on_done):
    dests = _all_destinations(exclude=current_exclude)
    if not dests:
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="No other destinations available.", font_size="14sp"))
        ok_btn = Button(text="OK", size_hint_y=None, height=44)
        content.add_widget(ok_btn)
        info_popup = Popup(title="Move / Copy", content=content, size_hint=(0.75, 0.3))
        ok_btn.bind(on_press=lambda x: info_popup.dismiss())
        info_popup.open()
        return

    content = BoxLayout(orientation="vertical", spacing=8, padding=12, size_hint_y=None)
    content.bind(minimum_height=content.setter("height"))
    inner_scroll = ScrollView(size_hint=(1, 1))
    inner_scroll.add_widget(content)
    title = "Move to..." if action == "move" else "Copy to..."
    menu_popup = Popup(title=title, content=inner_scroll, size_hint=(0.85, 0.75))

    for label, kind, lists_ref, idx in dests:
        btn = Button(text=label, size_hint_y=None, height=48, background_color=(0.35, 0.35, 0.35, 1))

        def do_pick(x, kind=kind, lists_ref=lists_ref, idx=idx):
            target_list = _dest_target_list(kind, lists_ref, idx)
            save_fn = _dest_save_fn(kind)
            new_item = _adapt_item_for_dest(item, kind)
            target_list.append(new_item)
            result = save_fn()
            menu_popup.dismiss()
            if result is not True:
                return
            if action == "move":
                remove_from_source()
            if on_done:
                on_done()

        btn.bind(on_press=do_pick)
        content.add_widget(btn)

    cancel_btn = Button(text="Cancel", size_hint_y=None, height=44)
    cancel_btn.bind(on_press=lambda x: menu_popup.dismiss())
    content.add_widget(cancel_btn)
    menu_popup.open()


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
        self.btn_article = Button(text="Article", font_size="13sp",
                                   background_color=(0.85, 0.5, 0.1, 1))
        self.btn_article.bind(on_press=lambda x: self.do_open_article_popup())
        row_mode.add_widget(self.btn_article)
        btn_task = Button(text="TASK", font_size="13sp",
                          background_color=(0.3, 0.55, 0.85, 1))
        btn_task.bind(on_press=self.do_open_task_popup)
        row_mode.add_widget(btn_task)
        btn_avatar2 = Button(text="Avatar 2", font_size="12sp",
                             background_color=(0.55, 0.35, 0.75, 1))
        btn_avatar2.bind(on_press=self.do_open_avatar2)
        row_mode.add_widget(btn_avatar2)
        self.add_widget(row_mode)

        # صف خاص بالبوست المُقتبَس (Shared Post)
        row1b = BoxLayout(size_hint_y=0.15)
        row1b.add_widget(Button(text="Quote Text", on_press=self.do_quote_text))
        row1b.add_widget(Button(text="Quote Link", on_press=self.do_quote_link))
        self.fetch_btn = Button(text="Fetch", font_size="12sp",
                                background_color=(0.15, 0.55, 0.65, 1))
        self.fetch_btn.bind(on_press=self.do_fetch_preview)
        row1b.add_widget(self.fetch_btn)
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

        Clock.schedule_interval(self._safe_capture, 1)
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

    def do_fetch_preview(self, x):
        """معاينة زي Raindrop.io: بياخد اللينك (من Quote Link المتحفّظ لو
        موجود، وإلا من اللينك المنتظر في الكليبورد)، وبيجيب og:image
        ويحطه كصورة البوست المقتبس واللينك تحتها - كل ده في ثريد منفصل
        عشان الواجهة متتجمدش."""
        url = (engine.quote_link or engine.pending or "").strip()
        if not url:
            self.status.text = "No link to fetch. Copy a link first (or press Quote Link)."
            return
        if not HAS_ARTICLE_DEPS:
            self.status.text = "❌ requests/beautifulsoup4 not installed in this build."
            return
        if self.fetch_btn.disabled:
            return

        self.fetch_btn.text = "Fetching..."
        self.fetch_btn.disabled = True
        self.status.text = "⏳ Fetching preview..."

        def worker():
            res = fetch_link_preview(url)
            Clock.schedule_once(lambda dt: self._on_preview_fetched(res, url), 0)

        threading.Thread(target=worker, daemon=True).start()

    def _on_preview_fetched(self, res, url):
        self.fetch_btn.text = "Fetch"
        self.fetch_btn.disabled = False

        if "error" in res:
            self.status.text = "❌ " + res["error"]
            return

        self._snapshot()
        engine.quote_images.append(res["image_path"])
        engine.grabbed.append(res["image_path"])
        if not engine.quote_link:
            engine.quote_link = url
        if engine.pending == url:
            engine.pending = ""
        engine.saved = False

        title = res.get("title")
        self.status.text = "✓ Preview fetched" + ((" — " + title) if title else "")
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

        confirm_btn = Button(text="Add Quote Avatar", background_color=(0.2, 0.65, 0.3, 1))
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
        already = set(engine.grabbed)
        candidates = []

        ms_path = get_latest_image_anywhere(exclude=already)
        if ms_path:
            candidates.append(ms_path)

        imgs = engine.get_new_images()
        if imgs:
            candidates.append(imgs[-1])  # آخر واحدة (الأحدث) من فحص الفولدرات، بما فيها Download

        if not candidates:
            msg = "No new images to add as avatar."
            if engine.last_scan_error:
                msg += "\n(" + engine.last_scan_error + ")"
            self.status.text = msg
            return

        # نقارن بالـ mtime الفعلي عشان لو صورة نزلت من المتصفح على فولدر
        # Download لسه ما اتفهرستش في MediaStore، برضه تتاخد لو هي فعلاً الأحدث.
        try:
            last_img = max(candidates, key=lambda p: os.path.getmtime(p))
        except Exception:
            last_img = candidates[0]
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
            try:
                thumb_b64, thumb_ext = make_thumbnail_b64(base64.b64decode(b64), _ext)
            except Exception:
                thumb_b64, thumb_ext = None, None
            new_avatar = {"name": name, "path": img_path, "ext": saved_ext,
                          "b64": ("" if img_path else b64),
                          "thumb_b64": thumb_b64, "thumb_ext": thumb_ext}

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
        popup = NamedAvatarListsPopup(SCROLL_LISTS, save_scroll_lists,
                                      title="📌 Scroll Lists", show_link=True,
                                      on_open_index=self._set_scroll_active, kind="scroll")
        popup.open()

    def _set_scroll_active(self, idx):
        global SCROLL_ACTIVE_LIST
        SCROLL_ACTIVE_LIST = idx
        sync_scroll_avatars_ref()
        save_scroll_lists()

    def do_open_avatar2(self, x):
        popup = NamedAvatarListsPopup(AVATAR2_LISTS, save_avatar2_lists,
                                      title="🅱 Avatar 2 Lists",
                                      on_select=self._set_avatar, kind="avatar2")
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

        name_row = BoxLayout(size_hint_y=None, height=40, spacing=8)
        self._name_display = Label(
            text=("Name: " + self._custom_post_name) if getattr(self, "_custom_post_name", "") else "Name: (auto)",
            font_size="12sp", halign="left", valign="middle"
        )
        self._name_display.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        name_btn = Button(text="Name", size_hint_x=None, width=90)
        name_row.add_widget(self._name_display)
        name_row.add_widget(name_btn)
        content.add_widget(name_row)

        content.add_widget(Label(text="Choose save format:", font_size="14sp"))
        btn_row = BoxLayout(size_hint_y=None, height=46, spacing=8)
        html_btn = Button(text="HTML")
        md_btn = Button(text="Markdown")
        both_btn = Button(text="Both")
        btn_row.add_widget(html_btn)
        btn_row.add_widget(md_btn)
        btn_row.add_widget(both_btn)
        content.add_widget(btn_row)
        cancel_btn = Button(text="Cancel", size_hint_y=None, height=40)
        content.add_widget(cancel_btn)

        choice_popup = Popup(title="Save Post", content=content, size_hint=(0.85, 0.4))
        name_btn.bind(on_press=lambda i: self._open_name_popup())
        html_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("html")))
        md_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("md")))
        both_btn.bind(on_press=lambda i: (choice_popup.dismiss(), self._do_save_format("both")))
        cancel_btn.bind(on_press=lambda i: choice_popup.dismiss())
        choice_popup.open()

    def _open_name_popup(self):
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(text="File name:", font_size="13sp", size_hint_y=None, height=24))
        name_input = TextInput(
            text=getattr(self, "_custom_post_name", ""),
            hint_text="e.g. my_post", multiline=False, size_hint_y=None, height=40
        )
        content.add_widget(name_input)
        btn_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        ok_btn = Button(text="OK", background_color=(0.2, 0.6, 0.35, 1))
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(ok_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)
        name_popup = Popup(title="Set File Name", content=content, size_hint=(0.8, 0.32))

        def confirm(inst):
            self._custom_post_name = name_input.text.strip()
            self._name_display.text = ("Name: " + self._custom_post_name) if self._custom_post_name else "Name: (auto)"
            name_popup.dismiss()

        ok_btn.bind(on_press=confirm)
        cancel_btn.bind(on_press=lambda i: name_popup.dismiss())
        name_popup.open()

    def _avatar_save_dir(self):
        """فولدر الحفظ الخاص بالأفاتار الحالي: /sdcard/Download/touch clip/<اسم_الأفاتار>/
        لو مفيش اسم أفاتار، يرجع لفولدر touch clip نفسه."""
        base = "/sdcard/Download"
        if not os.path.isdir(base) or not os.access(base, os.W_OK):
            base = os.path.join(os.path.expanduser("~"), "Download")

        base = os.path.join(base, "touch clip")

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

        custom_name = getattr(self, "_custom_post_name", "").strip()
        if custom_name:
            post_name = re.sub(r'[^\w\-\u0600-\u06FF ]', '_', custom_name).strip().replace(" ", "_") or "post"
        else:
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
  .comment-avatar-author {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background-size: cover;
    background-position: center;
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
""")
                if author_av_b64:
                    f.write(
                        '<style>.comment-avatar-author{background-image:url(data:image/'
                        + author_av_ext + ';base64,' + author_av_b64 + ');}</style>\n'
                    )
                f.write("""</head>
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
                            f.write('<div class="comment-avatar-author"></div>\n')
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
        الصور تُضمَّن داخل ملف الـ md نفسه كـ base64 data URI، بدون ملفات منفصلة."""

        def save_img_md(src_path):
            b64, ext = compress_to_b64_cached(src_path, img_cache)
            if not b64:
                return None
            return f"data:image/{ext};base64,{b64}"

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
        self._custom_post_name = ""
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
        global AVATARS, SCROLL_AVATARS, SCROLL_LISTS, SCROLL_ACTIVE_LIST, TASKS, AVATAR2_LISTS
        AVATARS.extend(load_avatars())
        loaded_lists, loaded_active = load_scroll_lists()
        SCROLL_LISTS.clear()
        SCROLL_LISTS.extend(loaded_lists)
        SCROLL_ACTIVE_LIST = loaded_active
        sync_scroll_avatars_ref()
        TASKS.extend(load_tasks())
        AVATAR2_LISTS.clear()
        AVATAR2_LISTS.extend(load_avatar2_lists())
        if not AVATAR2_LISTS:
            AVATAR2_LISTS.append({"name": "List 1", "avatars": []})
        # تنظيف لمرة واحدة: الأفاتارات القديمة كانت مخزّنة الصورة كاملة (base64)
        # جوه الملف *كمان* حتى لو الصورة موجودة أصلاً كملف على الديسك (path).
        # ده كان سبب تضخم avatars.json وبطء قراءته كل ما التطبيق يفتح من جديد.
        # هنا بنشيل التكرار: لو فيه path شغال، الملف نفسه كفاية.
        slim_legacy_avatar_blobs(AVATARS, save_avatars)
        scroll_changed = False
        for lst in SCROLL_LISTS:
            if slim_legacy_avatar_blobs(lst.get("avatars", []), None):
                scroll_changed = True
        if scroll_changed:
            save_scroll_lists()
        tasks_changed = False
        for task in TASKS:
            if slim_legacy_avatar_blobs(task.get("items", []), None):
                tasks_changed = True
        if tasks_changed:
            save_tasks(TASKS)
        avatar2_changed = False
        for lst in AVATAR2_LISTS:
            if slim_legacy_avatar_blobs(lst.get("avatars", []), None):
                avatar2_changed = True
        if avatar2_changed:
            save_avatar2_lists()

    def on_resume(self):
        """
        بتتنادى تلقائيًا من أندرويد لما التطبيق يرجع من الخلفية
        (يعني المستخدم نسخ من فيسبوك وبعدين رجع للتطبيق).
        بننادي _safe_capture فورًا هنا عشان النص يتلقط لحظة الرجوع
        مباشرة، من غير ما ننتظر الـ Clock.schedule_interval اللي بيفحص
        كل ثانيتين — ده اللي بيخلي التطبيق حاسس إنه بطيء لو رجعت بسرعة.
        """
        try:
            if self.root and hasattr(self.root, "_safe_capture"):
                self.root._safe_capture(0)
        except Exception:
            pass
        return True


MyApp().run()

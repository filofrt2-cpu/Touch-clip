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

import os, time, base64, copy, io, re, json, zipfile

try:
    from PIL import Image as PilImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# شريط التنقل السفلي للأندرويد يفضل ظاهر (fullscreen = 0 في buildozer.spec)
Window.softinput_mode = "below_target"

# طلب أذونات التخزين على أندرويد (لازم عشان GRAB/ATTACH/ADD يقدروا يقروا صور الجهاز)
try:
    from android.permissions import request_permissions, Permission, check_permission

    def request_android_permissions():
        perms = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
        # أندرويد 13+ (API 33) بيستخدم أذونات الميديا الجديدة
        for p in ("READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO"):
            if hasattr(Permission, p):
                perms.append(getattr(Permission, p))
        request_permissions(perms)

    def has_storage_permission():
        try:
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
        pass
    return []

def save_avatars():
    try:
        ensure_avatars_dir()
        with open(AVATARS_FILE, "w", encoding="utf-8") as f:
            json.dump(AVATARS, f, ensure_ascii=False)
        return True
    except Exception as e:
        return str(e)

def save_avatar_image(b64_data, ext, name):
    """حفظ الصورة كملف منفصل وإرجاع المسار"""
    ensure_avatars_dir()
    safe_name = re.sub(r"[^\w\-]", "_", name)
    filename = safe_name + "_" + str(int(time.time())) + "." + ext
    path = os.path.join(AVATARS_DIR, filename)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_data))
    return path

def export_avatars():
    try:
        with zipfile.ZipFile(AVATARS_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(AVATARS_FILE):
                zf.write(AVATARS_FILE, "avatars.json")
            missing = []
            for av in AVATARS:
                img_path = av.get("path", "")
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
        loaded = load_avatars()
        for av in loaded:
            if "path" in av:
                av["path"] = os.path.join(AVATARS_DIR, os.path.basename(av["path"]))
        AVATARS.clear()
        AVATARS.extend(loaded)
        save_avatars()
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
# ENGINE
# =========================
class Engine:
    def __init__(self):
        self.reset()

    def reset(self):
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
                if os.path.exists(fldr):
                    any_folder_found = True
                    for f in os.listdir(fldr):
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
            self.last_scan_error = "لم يتم العثور على مجلدات الصور - تحقق من إذن التخزين"

        return sorted(imgs, key=os.path.getmtime)


engine = Engine()


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

        grid = GridLayout(cols=3, size_hint_y=None, spacing=8, padding=8)
        grid.bind(minimum_height=grid.setter("height"))
        for idx, av in enumerate(AVATARS):
            cell = BoxLayout(orientation="vertical", size_hint_y=None, height=190)
            try:
                img_path = av.get("path", "")
                if img_path and os.path.exists(img_path):
                    core_img = CoreImage(img_path, ext=av.get("ext", "png"))
                else:
                    raw = base64.b64decode(av["b64"])
                    core_img = CoreImage(io.BytesIO(raw), ext=av.get("ext", "png"))
                img_widget = Image(texture=core_img.texture, size_hint_y=0.65)
            except Exception:
                img_widget = Label(text="?", size_hint_y=0.65)
            cell.add_widget(img_widget)

            # زرار الاختيار
            btn_select = Button(text=av.get("name", "No Name"), size_hint_y=0.18)
            btn_select.bind(on_press=lambda x, i=idx: self._pick(i))
            cell.add_widget(btn_select)

            # زرار الحذف
            btn_del = Button(text="🗑 Delete", size_hint_y=0.17,
                             background_color=(0.85, 0.2, 0.2, 1))
            btn_del.bind(on_press=lambda x, i=idx: self._delete(i))
            cell.add_widget(btn_del)

            grid.add_widget(cell)
        self.grid_container.add_widget(grid)

    def _pick(self, idx):
        self.on_select(AVATARS[idx])
        self.dismiss()

    def _delete(self, idx):
        av = AVATARS[idx]
        # حذف ملف الصورة من الجهاز لو موجود
        img_path = av.get("path", "")
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except Exception:
                pass
        AVATARS.pop(idx)
        save_avatars()
        self._refresh_grid()


# =========================
# NamePopup: يفتح بعد جلب صورة جديدة لكتابة اسم
# ويضيفها إلى AVATARS كعنصر جديد
# =========================
class NamePopup(Popup):
    def __init__(self, b64_data, ext, on_confirm, **kwargs):
        super().__init__(**kwargs)
        self.title = "Enter Avatar Name"
        self.size_hint = (0.85, 0.6)
        self.b64_data = b64_data
        self.on_confirm = on_confirm

        root = BoxLayout(orientation="vertical", spacing=8, padding=8)

        try:
            raw = base64.b64decode(b64_data)
            core_img = CoreImage(io.BytesIO(raw), ext=ext)
            img_widget = Image(texture=core_img.texture, size_hint_y=0.6)
            root.add_widget(img_widget)
        except Exception:
            root.add_widget(Label(text="(preview unavailable)", size_hint_y=0.6))

        self.name_input = TextInput(hint_text="اسم صاحب البوست", multiline=False, size_hint_y=0.15)
        root.add_widget(self.name_input)

        btn_row = BoxLayout(size_hint_y=0.15)
        confirm_btn = Button(text="Add")
        confirm_btn.bind(on_press=self._confirm)
        cancel_btn = Button(text="Cancel")
        cancel_btn.bind(on_press=lambda x: self.dismiss())
        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        self.content = root

    def _confirm(self, x):
        name = self.name_input.text.strip()
        if not name:
            return
        self.on_confirm(name, self.b64_data)
        self.dismiss()



# =========================
# ZIP FILE PICKER POPUP (وصول يدوي بالكامل)
# =========================
class ZipPickerPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = "تصفح واختر ملف ZIP يدوياً"
        self.size_hint = (0.95, 0.95)
        self.on_select = on_select

        root = BoxLayout(orientation="vertical", spacing=6, padding=8)

        # تحديد المسار الافتراضي الحقيقي لذاكرة الهاتف عند فتح المستعرض
        default_path = "/storage/emulated/0"
        if not os.path.exists(default_path):
            default_path = "/sdcard"

        # إنشاء مستعرض الملفات — بدون فلتر لضمان ظهور كل الملفات
        self.file_chooser = FileChooserListView(
            path=default_path,
            dirselect=False,
            show_hidden=False
        )
        root.add_widget(self.file_chooser)

        # أزرار التحكم السفلية
        btn_row = BoxLayout(size_hint_y=None, height=50, spacing=10)

        select_btn = Button(text="✅ اختيار الملف المحدد", background_color=(0.2, 0.6, 0.2, 1))
        select_btn.bind(on_press=self._validate_and_pick)

        cancel_btn = Button(text="إلغاء")
        cancel_btn.bind(on_press=lambda x: self.dismiss())

        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        self.content = root

    def _validate_and_pick(self, instance):
        selected = self.file_chooser.selection
        if not selected:
            return
        path = selected[0]
        if not path.lower().endswith(".zip"):
            return  # مش ZIP، متعملش حاجة
        self.dismiss()
        self.on_select(path)


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
        row1c.add_widget(Button(text="Import Avatars", on_press=self.do_import_avatars, font_size="11sp"))
        self.add_widget(row1c)

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

        Clock.schedule_interval(self._safe_capture, 0.8)
        self.update_status()

    def _update_status_text_size(self, instance, value):
        instance.text_size = (instance.width, instance.height)

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
        if len(engine.history) > 50:
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
            self.status.text = "مفيش نص في الانتظار."
            return
        self._snapshot()
        engine.quote_text = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_link(self, x):
        if not engine.pending:
            self.status.text = "مفيش لينك في الانتظار."
            return
        self._snapshot()
        engine.quote_link = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_img(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            self.status.text = "مفيش صور جديدة."
            return
        self._snapshot()
        engine.quote_images.extend(imgs)
        engine.grabbed.extend(imgs)
        engine.saved = False
        self.update_status()

    def do_quote_avatar(self, x):
        """جلب صورة بروفايل للبوست المقتبس من الجهاز مباشرة (زي ADD بس مش بتتحفظ في AVATARS)"""
        imgs = engine.get_new_images()
        if not imgs:
            msg = "مفيش صور جديدة للـ Quote Avatar."
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

        def on_confirm(name, b64):
            self._snapshot()
            engine.quote_author_name = name
            engine.quote_avatar_b64  = b64
            engine.quote_avatar_ext  = ext
            engine.saved = False
            self.update_status()

        popup = NamePopup(b64_data, ext, on_confirm=on_confirm)
        popup.open()

    def do_undo(self, x):
        if not engine.history:
            self.update_status()
            return
        s = engine.history.pop()
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
            target["imgs"].append(imgs[0])
            engine.grabbed.append(imgs[0])
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
        engine.author_avatar_ext = avatar.get("ext", "png")
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
            msg = "مفيش صور جديدة لإضافتها كأفاتار."
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

        def on_confirm(name, b64):
            try:
                img_path = save_avatar_image(b64, ext, name)
            except Exception as e:
                self.status.text = "❌ Image save failed: " + str(e)
                return
            new_avatar = {"name": name, "path": img_path, "ext": ext, "b64": b64}
            AVATARS.append(new_avatar)
            result = save_avatars()
            if result is True:
                self.status.text = "✓ Avatar saved: " + img_path
            else:
                self.status.text = "❌ Save failed: " + str(result)
            self._set_avatar(new_avatar)

        popup = NamePopup(b64_data, ext, on_confirm=on_confirm)
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
                self.status.text = "✓ Imported " + str(len(AVATARS)) + " avatars"
            else:
                self.status.text = "❌ Import failed: " + str(result)
        popup = ZipPickerPopup(on_select=on_zip_selected)
        popup.open()

    def do_save(self, x):
        if not engine.post and not engine.post_link:
            self.status.text = "Nothing to save yet."
            return

        clean = "".join(c for c in engine.post[:20] if c.isalnum() or c in " _").strip().replace(" ", "_")
        post_name = clean or "post"
        path      = "/sdcard/Download/" + post_name + ".html"

        MAX_PX   = 1080   # أقصى عرض/ارتفاع للصورة بعد الضغط
        QUALITY  = 65     # جودة JPEG
        AV_MAX   = 120    # حجم الأفاتار
        AV_QUAL  = 70

        def _kivy_compress(src_path, max_px, quality):
            """ضغط عبر Kivy CoreImage — يشتغل دايماً على أندرويد"""
            texture = CoreImage(src_path).texture
            w, h = texture.size
            # حساب النسبة
            scale = min(max_px / max(w, h, 1), 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            # Kivy مش بيعمل resize مباشرة، نستخدم PIL لو موجود وإلا نرجع الأصل
            if HAS_PIL:
                img = PilImage.open(src_path).convert("RGB")
                img.thumbnail((max_px, max_px), PilImage.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
            # Kivy فقط: نرجع الملف الأصلي مضغوطاً بـ re-encode بسيط
            buf = io.BytesIO(texture.pixels)
            return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"

        def compress_to_b64(src_path, max_px=MAX_PX, quality=QUALITY):
            try:
                if HAS_PIL:
                    img = PilImage.open(src_path).convert("RGB")
                    img.thumbnail((max_px, max_px), PilImage.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=quality, optimize=True)
                    return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
                # بدون PIL: نقرأ الملف ونرجعه raw — لكن نحذف الـ EXIF الكبير
                with open(src_path, "rb") as fp:
                    data = fp.read()
                # لو أكبر من 300KB نحاول نشيل EXIF يدوياً (JPEG فقط)
                if len(data) > 300_000 and data[:2] == b'\xff\xd8':
                    data = _strip_jpeg_exif(data)
                ext = os.path.splitext(src_path)[1].lower().lstrip(".") or "jpeg"
                if ext == "jpg":
                    ext = "jpeg"
                return base64.b64encode(data).decode("utf-8"), ext
            except Exception:
                return None, None

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

        def compress_av_b64(b64_data, ext_str):
            try:
                if HAS_PIL:
                    raw = base64.b64decode(b64_data)
                    img = PilImage.open(io.BytesIO(raw)).convert("RGB")
                    img.thumbnail((AV_MAX, AV_MAX), PilImage.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=AV_QUAL, optimize=True)
                    return base64.b64encode(buf.getvalue()).decode("utf-8"), "jpeg"
                # بدون PIL: الأفاتار بيتخزن كـ b64 أصلاً، نرجعه كما هو
                return b64_data, ext_str
            except Exception:
                return b64_data, ext_str

        try:
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
                        f.write(f'<div class="author-name">{engine.author_name}</div>\n')
                    f.write('</div>\n')

                post_html = engine.post.replace("\n", "<br>")
                f.write(f'<div class="post-body">{post_html}</div>\n')

                if engine.post_images:
                    f.write('<div class="post-images">\n')
                    for img in engine.post_images:
                        b64, ext = compress_to_b64(img)
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
                            f.write(f'<div class="quote-author-name">{engine.quote_author_name}</div>\n')
                        f.write('</div>\n')
                    if engine.quote_text:
                        quote_html = engine.quote_text.replace("\n", "<br>")
                        f.write(f'<div>{quote_html}</div>\n')
                    for img in engine.quote_images:
                        b64, ext = compress_to_b64(img)
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
                f.write('<div class="comments-title">التعليقات</div>\n')

                URL_RE = re.compile(r'(https?://[^\s<]+)')

                def linkify(text):
                    return URL_RE.sub(r'<a href="\1" target="_blank">\1</a>', text)

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
                            f.write(f'<div class="comment-name">{engine.author_name}</div>\n')
                        f.write(f'<div class="comment-bubble {css}">{text}')
                        for img in n["imgs"]:
                            b64, ext = compress_to_b64(img)
                            if b64:
                                f.write(f'<img src="data:image/{ext};base64,{b64}">')
                        f.write('</div>\n')
                        f.write('</div>\n')  # comment-body
                        f.write('</div>\n')  # comment-wrap

                        if n["replies"]:
                            rid = "rep_" + str(n["id"])
                            count = self._count_all(n["replies"])
                            f.write(f'<button class="replies-toggle" data-target="{rid}" onclick="toggleReplies(this)">'
                                    f'<span class="arrow">&#9660;</span>{count} ' + ("ردود" if count != 1 else "رد") + '</button>\n')
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

            engine.saved = True
            self.update_status()

        except Exception as e:
            self.status.text = "Error: " + str(e)

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
        return UI()

    def on_start(self):
        global AVATARS
        AVATARS.extend(load_avatars())


MyApp().run()

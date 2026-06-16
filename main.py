from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window

import os, time, base64, copy, io, re, json

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
def get_avatars_path():
    if os.path.exists("/sdcard/Download"):
        return "/sdcard/Download/.touchclip_avatars.json"
    return os.path.join(os.path.expanduser("~"), "avatars.json")

AVATARS_FILE = get_avatars_path()

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
        with open(AVATARS_FILE, "w", encoding="utf-8") as f:
            json.dump(AVATARS, f, ensure_ascii=False)
    except Exception:
        pass

AVATARS = load_avatars()


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

        root = BoxLayout(orientation="vertical")
        scroll = ScrollView()
        grid = GridLayout(cols=3, size_hint_y=None, spacing=8, padding=8)
        grid.bind(minimum_height=grid.setter("height"))

        if not AVATARS:
            empty = Label(text="No avatars available yet.\nAdd them to the AVATARS list in the code.")
            root.add_widget(empty)
        else:
            for idx, av in enumerate(AVATARS):
                cell = BoxLayout(orientation="vertical", size_hint_y=None, height=160)
                try:
                    raw = base64.b64decode(av["b64"])
                    core_img = CoreImage(io.BytesIO(raw), ext=av.get("ext", "png"))
                    img_widget = Image(texture=core_img.texture, size_hint_y=0.8)
                except Exception:
                    img_widget = Label(text="?", size_hint_y=0.8)
                cell.add_widget(img_widget)
                btn = Button(text=av.get("name", "No Name"), size_hint_y=0.2)
                btn.bind(on_press=lambda x, i=idx: self._pick(i))
                cell.add_widget(btn)
                grid.add_widget(cell)

        scroll.add_widget(grid)
        root.add_widget(scroll)
        close_btn = Button(text="Close", size_hint_y=0.1)
        close_btn.bind(on_press=lambda x: self.dismiss())
        root.add_widget(close_btn)
        self.content = root

    def _pick(self, idx):
        self.on_select(AVATARS[idx])
        self.dismiss()


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

        # صف خاص بالبوست المُقتبَس (Shared Post)
        row1b = BoxLayout(size_hint_y=0.15)
        row1b.add_widget(Button(text="Quote Text", on_press=self.do_quote_text))
        row1b.add_widget(Button(text="Quote Link", on_press=self.do_quote_link))
        row1b.add_widget(Button(text="Quote Img",  on_press=self.do_quote_img))
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
                    # بوست صورة فقط + لينك: أول نص منسوخ لينك بحت
                    engine.post_link = clip
                    engine.post_time = time.time()
                else:
                    engine.post      = clip
                    engine.post_time = time.time()
            elif not engine.post_link and is_pure_link:
                # لينك جه بعد ما النص اتسجل (بوست فيه نص + لينك)
                engine.post_link = clip
            elif "http" in clip:
                engine.pending = clip
            else:
                engine.pending = clip
            self.update_status()
        except Exception:
            pass

    def _snapshot(self):
        engine.history.append((copy.deepcopy(engine.comments),
                                self._node_id(engine.current_node),
                                self._node_id(engine.last_new),
                                self._node_id(engine.last_root)))

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
        engine.quote_text = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_link(self, x):
        if not engine.pending:
            self.status.text = "مفيش لينك في الانتظار."
            return
        engine.quote_link = engine.pending
        engine.pending    = ""
        engine.saved      = False
        self.update_status()

    def do_quote_img(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            self.status.text = "مفيش صور جديدة."
            return
        engine.quote_images.extend(imgs)
        engine.grabbed.extend(imgs)
        engine.saved = False
        self.update_status()

    def do_undo(self, x):
        if engine.history:
            comments, cur_id, last_new_id, last_root_id = engine.history.pop()
            engine.comments = comments
            engine.current_node = self._find_by_id(engine.comments, cur_id) if cur_id else None
            engine.last_new = self._find_by_id(engine.comments, last_new_id) if last_new_id else None
            engine.last_root = self._find_by_id(engine.comments, last_root_id) if last_root_id else None
        self.update_status()

    def do_grab(self, x):
        imgs = engine.get_new_images()
        if imgs:
            engine.post_images.extend(imgs)
            engine.grabbed.extend(imgs)
        self.update_status()

    def do_attach(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            return
        target = engine.current_node or (engine.comments[-1] if engine.comments else None)
        if target:
            target["imgs"].append(imgs[0])
            engine.grabbed.append(imgs[0])
            engine.saved = False
        self.update_status()

    # ----------------------------------------
    # Attach Link: يضاف إلى نهاية صور البوست (post_images)
    # ----------------------------------------
    def do_attach_link(self, x):
        imgs = engine.get_new_images()
        if not imgs:
            return
        engine.post_images.append(imgs[0])
        engine.grabbed.append(imgs[0])
        engine.saved = False
        self.update_status()

    # ----------------------------------------
    # اختيار صورة البروفايل (avatar) + الاسم المرتبط بها
    # ----------------------------------------
    def do_pick_avatar(self, x):
        popup = AvatarPopup(on_select=self._set_avatar)
        popup.open()

    def _set_avatar(self, avatar):
        engine.author_name = avatar.get("name", "")
        engine.author_avatar_b64 = avatar.get("b64", "")
        engine.author_avatar_ext = avatar.get("ext", "png")
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
        engine.grabbed.extend(imgs)
        ext = os.path.splitext(last_img)[1].lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        try:
            b64_data = base64.b64encode(open(last_img, "rb").read()).decode("utf-8")
        except Exception as e:
            self.status.text = "Error reading image: " + str(e)
            return

        def on_confirm(name, b64):
            new_avatar = {"name": name, "b64": b64, "ext": ext}
            AVATARS.append(new_avatar)
            save_avatars()
            self._set_avatar(new_avatar)

        popup = NamePopup(b64_data, ext, on_confirm=on_confirm)
        popup.open()

    def do_save(self, x):
        if not engine.post:
            self.status.text = "Nothing to save yet."
            return

        clean = "".join(c for c in engine.post[:20] if c.isalnum() or c in " _").strip().replace(" ", "_")
        path  = "/sdcard/Download/" + (clean or "post") + ".html"

        try:
            with open(path, "w", encoding="utf-8") as f:

                favicon_tag = ""
                if engine.author_avatar_b64:
                    favicon_tag = f'<link rel="icon" type="image/{engine.author_avatar_ext}" href="data:image/{engine.author_avatar_ext};base64,{engine.author_avatar_b64}">\n'

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
                if engine.author_avatar_b64 or engine.author_name:
                    f.write('<div class="post-header">\n')
                    if engine.author_avatar_b64:
                        f.write(f'<img class="avatar" src="data:image/{engine.author_avatar_ext};base64,{engine.author_avatar_b64}">\n')
                    if engine.author_name:
                        f.write(f'<div class="author-name">{engine.author_name}</div>\n')
                    f.write('</div>\n')

                post_html = engine.post.replace("\n", "<br>")
                f.write(f'<div class="post-body">{post_html}</div>\n')

                if engine.post_images:
                    f.write('<div class="post-images">\n')
                    for img in engine.post_images:
                        try:
                            b = base64.b64encode(open(img, "rb").read()).decode("utf-8")
                            f.write(f'<img src="data:image/jpeg;base64,{b}">\n')
                        except Exception:
                            pass
                    f.write('</div>\n')

                if engine.quote_text or engine.quote_link or engine.quote_images:
                    f.write('<div class="quote-post">\n')
                    if engine.quote_text:
                        quote_html = engine.quote_text.replace("\n", "<br>")
                        f.write(f'<div>{quote_html}</div>\n')
                    for img in engine.quote_images:
                        try:
                            b = base64.b64encode(open(img, "rb").read()).decode("utf-8")
                            f.write(f'<img src="data:image/jpeg;base64,{b}">\n')
                        except Exception:
                            pass
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
                    prev_role = None
                    for idx, n in enumerate(nodes):
                        role = n["role"]
                        if role in ("author", "link_author", "new", "link"):
                            css = role
                        else:
                            css = "link"

                        text = linkify(n["text"]).replace("\n", "<br>")
                        is_owner = role in ("author", "link_author")
                        show_identity = True
                        prev_role = role

                        wrap_class = "comment-wrap"
                        if is_root and idx > 0:
                            wrap_class += " new-thread"

                        f.write(f'<div class="{wrap_class}">\n')
                        if is_owner and engine.author_avatar_b64 and show_identity:
                            f.write(f'<img class="comment-avatar" src="data:image/{engine.author_avatar_ext};base64,{engine.author_avatar_b64}">\n')
                        f.write('<div class="comment-body">\n')
                        if is_owner and engine.author_name and show_identity:
                            f.write(f'<div class="comment-name">{engine.author_name}</div>\n')
                        f.write(f'<div class="comment-bubble {css}">{text}')
                        for img in n["imgs"]:
                            try:
                                b = base64.b64encode(open(img, "rb").read()).decode("utf-8")
                                f.write(f'<img src="data:image/jpeg;base64,{b}">')
                            except Exception:
                                pass
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


MyApp().run()

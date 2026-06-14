تمام! دلوقتي:

**1. في خانة "Name your file..." اكتب:**
```
buildozer.spec
```

**2. في المنطقة الكبيرة "Enter file contents here" الصق الكود ده:**

```ini
[app]
title = Touch Clip
package.name = touchclip
package.domain = org.touchclip
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0
requirements = python3,kivy
orientation = portrait
android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.ndk = 25b

[buildozer]
log_level = 2
```

**3. بعدين اضغط "Commit changes"** ✅

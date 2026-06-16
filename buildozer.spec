[app]
title = Post Builder
package.name = postbuilder
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

requirements = python3,kivy,pillow

orientation = portrait
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO

android.api = 35
android.minapi = 26
android.ndk = 28c
android.archs = arm64-v8a

[buildozer]
log_level = 2

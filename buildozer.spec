[app]
title = Post Builder
package.name = postbuilder
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

requirements = python3,kivy,pillow,requests,beautifulsoup4==4.12.3,certifi,urllib3,charset-normalizer,idna,html5lib

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,MANAGE_EXTERNAL_STORAGE

android.api = 34
android.minapi = 26
android.ndk = 26b
android.archs = arm64-v8a

[buildozer]
log_level = 2

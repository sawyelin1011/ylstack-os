#!/system/bin/sh
# YL StackOS — Userspace container mount script
# Mounts the userspace (second chroot) inside the main container

CONTAINERROOT="/container/userspace"

mount --bind /dev "$CONTAINERROOT/dev"
mount -t devpts devpts "$CONTAINERROOT/dev/pts"
mount -t tmpfs -o size=256M tmpfs "$CONTAINERROOT/dev/shm"
mount --bind /sys "$CONTAINERROOT/sys"
mount --bind /proc "$CONTAINERROOT/proc"
mount --bind /sdcard "$CONTAINERROOT/sdcard"
mount --bind /ylstackos "$CONTAINERROOT/ylstackos"
mount --bind /ylstackosext "$CONTAINERROOT/ylstackosext"
mount --bind /usr/local/ylstackos/bin "$CONTAINERROOT/usr/local/ylstackos/bin"
mount --bind / "$CONTAINERROOT/ylstackosroot"

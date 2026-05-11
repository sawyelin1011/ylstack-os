#!/system/bin/sh
# YL StackOS — Userspace container unmount script

CONTAINERROOT="/container/userspace"

umount "$CONTAINERROOT/dev/shm"  2>/dev/null
umount "$CONTAINERROOT/dev/pts"  2>/dev/null
umount "$CONTAINERROOT/dev"      2>/dev/null
umount "$CONTAINERROOT/proc"     2>/dev/null
umount "$CONTAINERROOT/sys"      2>/dev/null
umount "$CONTAINERROOT/sdcard"   2>/dev/null
umount "$CONTAINERROOT/ylstackos" 2>/dev/null
umount "$CONTAINERROOT/ylstackosext" 2>/dev/null

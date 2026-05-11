#!/bin/bash
# YL StackOS — WINE WebVNC launcher
# Starts WINE app inside VNC session

export WINE_FULLSCREEN_DESKTOP=1
bit_version=$1
geometry=$2
program=$3

openbox-session &
xset -r
xsetroot -solid grey -cursor_name left_ptr

EXT="/ylstackosext"
[ ! -d "$EXT" ] && EXT="/flyosext"

case "$bit_version" in
    86)
        "$EXT/wine/startwine86" explorer /desktop=shell,"$geometry" "$program"
        ;;
    64)
        "$EXT/wine/startwine64" explorer /desktop=shell,"$geometry" "$program"
        ;;
    *)
        echo "Invalid bit version. Must be 86 or 64."
        exit 1
        ;;
esac

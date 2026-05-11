#!/bin/bash
# YL StackOS — Android screen mirror via scrcpy
openbox-session &
xset -r
xsetroot -solid grey -cursor_name left_ptr
/usr/bin/scrcpy --fullscreen --always-on-top --window-borderless --window-width=1280 --window-height=720

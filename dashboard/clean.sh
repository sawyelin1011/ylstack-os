#!/bin/bash
apt update
apt upgrade -y
apt clean
apt autoremove -y
userspace cmd --cmd 'apt update'
userspace cmd --cmd 'apt upgrade -y'
userspace cmd --cmd 'apt clean'
userspace cmd --cmd 'apt autoremove -y'
rm -rf logs/*
rm -rf /root/.bash_history
rm -rf /container/userspace/root/.bash_history
rm -rf /var/lib/apt/lists/*
rm -rf /container/userspace/var/lib/apt/lists/*
rm -rf /container/userspace/root/.cache/*
echo > /ylstackos/files/pwd.conf
rm -rf /ylstackos/files/setup/setup_lock
rm -rf /container/userspace/root/.mozilla/firefox-esr
rm -rf /ylstackos/logs/*
rm -rf /root/.cache
rm -rf /root/.vnc/*.log
rm -rf /root/.vnc/*.pid
rm -rf /container/userspace/root/.vnc/*.log
rm -rf /container/userspace/root/.vnc/*.pid
rm -rf /var/log/*
rm -rf /container/userspace/var/log/*
rm -rf /var/tmp/*
rm -rf /tmp/*
rm -rf /container/userspace/var/tmp/*
rm -rf /container/userspace/tmp/*
rm -rf /ylstackos/nohup.out
rm -rf /boot/scripts/*
rm -rf /root/.local/share/code-server
echo > /ylstackos/files/token/token
echo > /ylstackos/files/temp/otp
echo root:ylstackospwd | chpasswd
echo ylstack:userpassword | chpasswd
cp /ylstackos/config.py /ylstackos/files/backup/config.py
rm -rf /var/cache/apt/*.bin
rm -rf /container/userspace/var/cache/apt/*.bin

#!/bin/sh
# Removes the e-Paper Panel client and what it kept (its key, its last page).
# Run as root by Update Your Kindle. epaper-panel.txt on the drive is left for you.

[ -x /usr/local/epaper-panel/epaper-panel.sh ] && /usr/local/epaper-panel/epaper-panel.sh stop
/usr/sbin/mntroot rw
rm -f /etc/rc5.d/S99epaper-panel /etc/init.d/epaper-panel
rm -rf /usr/local/epaper-panel
sync
/usr/sbin/mntroot ro
rm -rf /var/local/epaper-panel
exit 0

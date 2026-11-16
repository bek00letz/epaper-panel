#!/bin/sh
# Installs the e-Paper Panel client. Run as root by Update Your Kindle, from
# the folder the package was unpacked into. Its way back is the uninstall package.

/usr/sbin/mntroot rw
mkdir -p /usr/local/epaper-panel
cp -f epaper-panel.sh /usr/local/epaper-panel/epaper-panel.sh
chmod 0755 /usr/local/epaper-panel/epaper-panel.sh
cp -f epaper-panel.init /etc/init.d/epaper-panel
chmod 0755 /etc/init.d/epaper-panel
ln -sf /etc/init.d/epaper-panel /etc/rc5.d/S99epaper-panel
sync
/usr/sbin/mntroot ro

# Where it finds the add-on: the file from the editor, copied next to this
# package; otherwise one to fill in. An existing one is kept.
if [ ! -f /mnt/us/epaper-panel.txt ]; then
    cat > /mnt/us/epaper-panel.txt <<'TXT'
# E-paper panel: where this Kindle finds your pages.
# Add the Kindle in the e-Paper editor in Home Assistant (Add new device, Kindle):
# it shows the address to put after "server =", or gives you this file filled in.
server =
TXT
fi
mkdir -p /var/local/epaper-panel
echo "$(date '+%Y-%m-%d %H:%M:%S') installed" >> /var/local/epaper-panel/log
exit 0

Create a .desktop file (e.g. battery_tray.desktop) in ~/.config/autostart:  
```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/battery_tray.desktop
```

Put something like this in that file:  
```ini
[Desktop Entry]
Type=Application
Name=Battery Tray
Exec=/home/youruser/bin/battery_tray.py
# If you want to hide it from certain DEs, you can use:
# OnlyShowIn=GNOME;Unity;Xfce;LXDE;KDE;
X-GNOME-Autostart-enabled=true
```

Make your Python script executable (if it isn’t already):  
```bash
chmod +x /home/youruser/bin/battery_tray.py
```

Log out and log in. Your tray script should run automatically, and you’ll see its icon in your system tray.

That’s it! This is typically the simplest method for a single user who wants an app to appear in their tray each session.

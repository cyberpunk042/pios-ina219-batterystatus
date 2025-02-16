#!/usr/bin/env python3
"""
Usage:
    sudo python3 install.py <TARGET_USER>

Example:
    sudo python3 install.py pi

This script will:
 1) Copy batteryStatus.py, batteryService.py, and battery_*.png
    from the current directory into /home/<TARGET_USER>/pios-ina219-batterystatus.
 2) Make them executable.
 3) Convert relative icon paths QIcon("battery_...") to absolute paths
    in the newly copied batteryStatus.py.  (Also does batteryService.py if you want.)
 4) Create ~/.config/autostart/batteryStatus.desktop so that the user's
    desktop session auto-launches the battery monitor at login (Pi OS).
 5) Set file ownership to <TARGET_USER>.
"""

import sys
import os
import shutil
import glob
import pwd
import stat

def fix_icon_paths(script_path, install_folder):
    """
    Reads 'script_path' and replaces occurrences of:
      QIcon("battery_
    with
      QIcon("<install_folder>/battery_
    so that they point to the absolute path.
    """
    if not os.path.exists(script_path):
        return  # File doesn't exist, do nothing.

    with open(script_path, "r") as f:
        content = f.read()

    # We'll do a simple string replace. For example:
    # QIcon("battery_ => QIcon("/home/pi/pios-ina219-batterystatus/battery_
    new_content = content.replace(
        'QIcon("battery_',
        f'QIcon("{install_folder}/battery_'
    )

    if new_content != content:
        with open(script_path, "w") as f:
            f.write(new_content)
        print(f"Fixed icon paths in {script_path}")
    else:
        print(f"No icon references changed in {script_path}")

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <TARGET_USER>")
        sys.exit(1)

    target_user = sys.argv[1]
    try:
        user_info = pwd.getpwnam(target_user)
    except KeyError:
        print(f"Error: user '{target_user}' does not exist.")
        sys.exit(1)

    if os.geteuid() != 0:
        print("Warning: Not running as root. "
              "You may not have permission to chown files for another user.")
        # You could enforce root usage if desired
        # sys.exit(1)

    uid = user_info.pw_uid
    gid = user_info.pw_gid
    home_dir = user_info.pw_dir  # e.g. "/home/pi"

    install_dir = os.path.join(home_dir, "pios-ina219-batterystatus")
    autostart_dir = os.path.join(home_dir, ".config", "autostart")
    desktop_file = os.path.join(autostart_dir, "batteryStatus.desktop")

    print(f"Installing for user: {target_user}")
    print(f"INSTALL_DIR:     {install_dir}")
    print(f"AUTOSTART FILE:  {desktop_file}")

    # 1) Create target directories
    os.makedirs(install_dir, exist_ok=True)
    os.makedirs(autostart_dir, exist_ok=True)

    # 2) Copy Python scripts + icons
    anything_copied = False
    scripts_to_copy = ["batteryStatus.py", "batteryService.py"]

    for script in scripts_to_copy:
        if os.path.exists(script):
            shutil.copy(script, install_dir)
            print(f"Copied {script} -> {install_dir}")
            anything_copied = True
        else:
            print(f"Note: {script} not found; skipping.")

    png_files = glob.glob("battery_*.png")
    if png_files:
        for png in png_files:
            shutil.copy(png, install_dir)
            print(f"Copied {png} -> {install_dir}")
        anything_copied = True
    else:
        print("No battery_*.png icons found; skipping icons.")

    if not anything_copied:
        print("Warning: No files were copied. Are you running in the correct directory?")

    # 3) Make .py files executable
    for script in scripts_to_copy:
        script_path = os.path.join(install_dir, script)
        if os.path.exists(script_path):
            st = os.stat(script_path)
            os.chmod(
                script_path,
                st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            print(f"Set +x on {script_path}")

    # 4) Fix icon paths in batteryStatus.py (and batteryService.py if needed)
    #    because we want QIcon("<absolute path>/battery_0.png") etc.
    for script in scripts_to_copy:
        script_path = os.path.join(install_dir, script)
        fix_icon_paths(script_path, install_dir)

    # 5) Create the .desktop file in ~/.config/autostart
    # By default, we run batteryStatus.py with 'sudo'. If you don't need root, remove 'sudo'.
    run_script = os.path.join(install_dir, "batteryStatus.py")
    if not os.path.exists(run_script):
        # If batteryStatus.py wasn't found, fall back to batteryService.py
        alt_script = os.path.join(install_dir, "batteryService.py")
        if os.path.exists(alt_script):
            run_script = alt_script
        else:
            print("Warning: No main script found to run in .desktop file.")
            run_script = ""

    if run_script:
        desktop_contents = f"""[Desktop Entry]
Type=Application
Name=Battery Status
Comment=Auto-launch battery monitor
Exec=bash -c "sleep 5; python3 {run_script}"
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        with open(desktop_file, "w") as f:
            f.write(desktop_contents)
        print(f"Created autostart .desktop -> {desktop_file}")

    # 6) Chown everything to <target_user>
    def chown_recursive(path, uid, gid):
        for root, dirs, files in os.walk(path):
            for d in dirs:
                os.chown(os.path.join(root, d), uid, gid)
            for filename in files:
                os.chown(os.path.join(root, filename), uid, gid)
        os.chown(path, uid, gid)

    if os.path.exists(install_dir):
        chown_recursive(install_dir, uid, gid)
    if os.path.exists(desktop_file):
        os.chown(desktop_file, uid, gid)

    print("--------------------------------------------")
    print("Installation complete!")
    print(f"User:          {target_user}")
    print(f"Scripts:       {install_dir}")
    print(f"Autostart file:{desktop_file}")
    print("")
    print("On next GUI login, your battery script will launch automatically.")
    print("If you do NOT need root, remove 'sudo' in the Exec= line.")
    print("--------------------------------------------")


if __name__ == "__main__":
    main()

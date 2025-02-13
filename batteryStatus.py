#!/usr/bin/env python3

import sys
import time
import logging
import smbus
import os

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMenu,
    QAction,
)
from PyQt5.QtCore import (
    QObject,
    QThread,
    pyqtSignal,
    QMutex,
)

########################################
#  Custom INA219 class (no pip needed) #
########################################
I2C_ADDRESS = 0x41  # Change if needed
_REG_BUSVOLTAGE = 0x02
SYSFS_BATTERY_CAPACITY_PATH = "/sys/class/power_supply/BAT0/capacity"
FALLBACK_PATH = "/tmp/battery_status"

class INA219:
    def __init__(self, i2c_bus=1, addr=I2C_ADDRESS):
        self.bus = smbus.SMBus(i2c_bus)
        self.addr = addr

    def read_voltage(self):
        """Reads the bus voltage from INA219 in volts."""
        try:
            data = self.bus.read_i2c_block_data(self.addr, _REG_BUSVOLTAGE, 2)
            raw = ((data[0] << 8) | data[1]) >> 3
            return raw * 0.004  # each bit = 4mV
        except Exception as e:
            print(f"Error reading voltage: {e}")
            return None

def write_battery_percentage(percentage):
    """Writes battery percentage to sysfs or fallback file."""
    percentage = int(max(0, min(100, percentage)))  # clamp 0-100

    # Try writing to sysfs first
    try:
        with open(SYSFS_BATTERY_CAPACITY_PATH, "w") as f:
            f.write(f"{percentage}\n")
        print(f"Updated battery percentage: {percentage}% in sysfs")
        return
    except PermissionError:
        print("Warning: no permission to write to sysfs. Try sudo if you really need sysfs updates.")
    except FileNotFoundError:
        print(f"Sysfs path {SYSFS_BATTERY_CAPACITY_PATH} not found.")

    # Fallback to /tmp file
    try:
        with open(FALLBACK_PATH, "w") as f:
            f.write(f"{percentage}\n")
        print(f"Updated battery percentage: {percentage}% in {FALLBACK_PATH}")
    except Exception as e:
        print(f"Error writing battery percentage: {e}")

########################################
# Global state / script boilerplate
########################################

mustHalt = False
mutex = QMutex()

def halt():
    global mustHalt
    global mutex
    mutex.lock()
    mustHalt = True
    mutex.unlock()

logging.basicConfig(format="%(message)s", level=logging.INFO)

########################################
#  Worker class that runs in a QThread
########################################
class Worker(QObject):
    finished = pyqtSignal()
    trayMessage = pyqtSignal(int, float, float)  # (icon_index, voltage, percentage)
    logMessage = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ina = INA219()  # your custom INA219 class

    def run(self):
        """
        Main loop: read the voltage, compute battery %,
        choose an icon, emit signals, and optionally write to sysfs/fallback.
        """
        global mustHalt, mutex
        while True:
            # Check if we should halt
            mutex.lock()
            mh = mustHalt
            mutex.unlock()
            if mh:
                break

            bus_voltage = self.ina.read_voltage()
            if bus_voltage is not None:
                # Example: 9.0 V -> 0%, 12.6 V -> 100%
                percentage = (bus_voltage - 9.0) / 3.6 * 100
                percentage = max(0, min(100, percentage))

                # Decide which battery icon (0–7 for empty→full, etc.)
                icon_index = self.pick_icon(bus_voltage)

                # Emit so the tray updates
                self.trayMessage.emit(icon_index, bus_voltage, percentage)

                # Write battery % to sysfs or fallback
                write_battery_percentage(percentage)

            else:
                # If read_voltage() returned None, we can show an alert icon
                icon_index = 9  # "battery_alert.png"
                self.trayMessage.emit(icon_index, 0.0, 0.0)
                self.logMessage.emit("INA219: read error, showing alert icon")

            time.sleep(5)  # poll every 5 seconds

        self.finished.emit()

    def pick_icon(self, voltage):
        """
        Given the measured voltage, return an icon index [0..10].
        For consistency with your original icon set:
            0 => battery_0.png (lowest)
            1 => battery_1.png
            ...
            7 => battery_7.png (full)
            8 => battery_charging.png
            9 => battery_alert.png
            10 => battery_unknown.png
        Here, we only do the non-charging states 0..7 or use 9 for super low.
        Feel free to adjust thresholds as you like.
        """
        if voltage < 9.0:
            return 0  # dangerously low
        elif voltage < 9.4:
            return 0
        elif voltage < 9.8:
            return 1
        elif voltage < 10.2:
            return 2
        elif voltage < 10.6:
            return 3
        elif voltage < 11.0:
            return 4
        elif voltage < 11.4:
            return 5
        elif voltage < 11.8:
            return 6
        elif voltage <= 12.6:
            return 7
        else:
            # If above 12.6, we might show full
            return 7

########################################
#  Main application (PyQt tray icon)
########################################
def message(msg):
    logging.info("Message: " + str(msg))

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

icons = [
    QIcon("battery_0.png"),        # 0
    QIcon("battery_1.png"),        # 1
    QIcon("battery_2.png"),        # 2
    QIcon("battery_3.png"),        # 3
    QIcon("battery_4.png"),        # 4
    QIcon("battery_5.png"),        # 5
    QIcon("battery_6.png"),        # 6
    QIcon("battery_7.png"),        # 7
    QIcon("battery_charging.png"), # 8 - not used in this example unless you add charging logic
    QIcon("battery_alert.png"),    # 9
    QIcon("battery_unknown.png"),  # 10
]

iconnames = [
    "Empty",      # 0
    "Low",        # 1
    "29%",        # 2
    "43%",        # 3
    "57%",        # 4
    "71%",        # 5
    "86%",        # 6
    "Full",       # 7
    "Charging",   # 8
    "Alert",      # 9
    "Unknown",    # 10
]

tray = QSystemTrayIcon()
tray.setIcon(icons[10])  # start with "unknown"
tray.setVisible(True)

def changeBatteryStatus(icon_index, voltage, percentage):
    tray.setIcon(icons[icon_index])
    s = f"{percentage:.1f}% ({voltage:.2f}V)"
    tray.setToolTip(s)

    localTime = time.localtime(time.time())
    logging.info(
        f"{localTime.tm_year:04d}-{localTime.tm_mon:02d}-{localTime.tm_mday:02d} "
        f"{localTime.tm_hour:02d}:{localTime.tm_min:02d}:{localTime.tm_sec:02d} "
        f"Icon: {icon_index} ({iconnames[icon_index]}) ToolTip: {s}"
    )

# Threading
thread = QThread()
worker = Worker()
worker.moveToThread(thread)

thread.started.connect(worker.run)
worker.finished.connect(thread.quit)
worker.finished.connect(worker.deleteLater)
worker.finished.connect(app.quit)
thread.finished.connect(thread.deleteLater)

worker.trayMessage.connect(changeBatteryStatus)
worker.logMessage.connect(message)

# Create tray menu
menu = QMenu()
quit_action = QAction("Quit")
quit_action.triggered.connect(halt)
menu.addAction(quit_action)
tray.setContextMenu(menu)

# Start the worker thread
thread.start()
sys.exit(app.exec_())

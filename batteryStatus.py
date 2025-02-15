#!/usr/bin/env python3

import sys
import time
import logging
import os

import smbus

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

#############################
# INA219 Class (Accurate)  #
#############################

# Register addresses
_REG_CONFIG       = 0x00
_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE   = 0x02
_REG_POWER        = 0x03
_REG_CURRENT      = 0x04
_REG_CALIBRATION  = 0x05

class INA219:
    """
    Improved INA219 interface:
      - Properly configures bus voltage range and ADC settings
      - Calibrates for expected max current + known shunt resistor
      - Provides read_bus_voltage(), read_shunt_voltage(), read_current()
    """
    def __init__(self, address=0x40, i2c_bus=1, shunt_ohms=0.1, max_expected_amps=3.2):
        self.bus = smbus.SMBus(i2c_bus)
        self.address = address
        self.shunt_ohms = shunt_ohms
        self.max_expected_amps = max_expected_amps

        self.configure()
        self.calibrate()

    def configure(self):
        """
        Example config:
         - Bus voltage range = 16V (BRNG=0)
         - Gain = /1 (±40mV) (PG=00)
         - Bus ADC = 12-bit (BADC=1111)
         - Shunt ADC = 12-bit (SADC=1111)
         - Mode = continuous shunt and bus (MODE=111)
        """
        brng = 0  # 0 => 16V range
        pg = 0    # 0 => gain /1 (±40 mV)
        badc = 0xF  # 1111 => 12-bit (sample)
        sadc = 0xF  # 1111 => 12-bit (sample)
        mode = 0x7  # 111 => continuous shunt & bus

        config = ((brng & 0x1) << 13) \
               | ((pg & 0x3) << 11)   \
               | ((badc & 0xF) << 7)  \
               | ((sadc & 0xF) << 3)  \
               | (mode & 0x7)

        self._write_register(_REG_CONFIG, config)

    def calibrate(self):
        """
        Calibrate based on max expected current and shunt resistor.
        This sets up the INA219 so that CURRENT register readings are scaled properly.
        """
        # Current LSB:  max_current / 32767
        current_lsb = self.max_expected_amps / 32767.0
        # Calibration value
        cal = int(0.04096 / (current_lsb * self.shunt_ohms))

        self._write_register(_REG_CALIBRATION, cal)

        # Store the actual current LSB for later current calculations
        self.current_lsb = 0.04096 / (cal * self.shunt_ohms)

    def read_bus_voltage(self):
        """
        Read the bus voltage (in volts). For a 16V range, each bit = 4mV.
        The register's lower 3 bits are not used for voltage data.
        """
        raw = self._read_register(_REG_BUSVOLTAGE)
        raw >>= 3  # drop CNVR/OVF bits
        voltage = raw * 0.004  # 4 mV per bit
        return voltage

    def read_shunt_voltage(self):
        """Returns the shunt voltage in volts."""
        raw = self._read_register_signed(_REG_SHUNTVOLTAGE)
        # By default LSB = 10µV = 0.00001V if gain=1
        return raw * 0.00001

    def read_current(self):
        """Returns the current in amperes."""
        raw = self._read_register_signed(_REG_CURRENT)
        return raw * self.current_lsb

    def _read_register(self, reg):
        """Read 16-bit unsigned from 'reg' (account for endianness)."""
        val = self.bus.read_word_data(self.address, reg)
        return self._swap_bytes(val) & 0xFFFF

    def _read_register_signed(self, reg):
        """Read 16-bit signed from 'reg'."""
        val = self._read_register(reg)
        if val & 0x8000:  # sign bit
            return -((val ^ 0xFFFF) + 1)
        return val

    def _write_register(self, reg, value):
        """Write 16-bit, accounting for endianness."""
        self.bus.write_word_data(self.address, reg, self._swap_bytes(value))

    def _swap_bytes(self, word_val):
        """Swap low/high byte because SMBus is typically little-endian."""
        return ((word_val << 8) & 0xFF00) | (word_val >> 8)

#############################
# Global Vars and Settings #
#############################

I2C_ADDRESS = 0x41   # Your INA219 I2C address (often 0x40 or 0x41)
I2C_BUS = 1          # e.g. Raspberry Pi uses bus=1
SHUNT_OHMS = 0.1     # e.g. a 0.1 Ω shunt
MAX_CURRENT = 3.2    # Max expected current in amps
POLL_INTERVAL = 5    # Seconds between updates

# For demonstration: battery = 3S Li-ion => ~9.0 V (empty) to ~12.6 V (full)
MIN_VOLTAGE = 9.0
MAX_VOLTAGE = 12.6

# SysFS or fallback file (optional) if you want to write battery percentage somewhere
SYSFS_BATTERY_CAPACITY_PATH = "/sys/class/power_supply/BAT0/capacity"
FALLBACK_PATH = "/tmp/battery_status"

# If you want logging info in the console:
logging.basicConfig(format="%(message)s", level=logging.INFO)

#############################
# Utility function to write %
# battery % to sysfs        #
#############################
def write_battery_percentage(percentage):
    """
    Example: tries to write battery percentage to a sysfs file, then fallback to /tmp.
    Clamp percentage to [0..100].
    """
    percentage = int(max(0, min(100, percentage)))  # clamp
    try:
        with open(SYSFS_BATTERY_CAPACITY_PATH, "w") as f:
            f.write(f"{percentage}\n")
        print(f"Updated battery percentage: {percentage}% in sysfs ({SYSFS_BATTERY_CAPACITY_PATH})")
        return
    except PermissionError:
        print("Warning: no permission to write to sysfs. Try sudo if needed.")
    except FileNotFoundError:
        print(f"Sysfs path {SYSFS_BATTERY_CAPACITY_PATH} not found.")

    # fallback
    try:
        with open(FALLBACK_PATH, "w") as f:
            f.write(f"{percentage}\n")
        print(f"Updated battery percentage: {percentage}% in {FALLBACK_PATH}")
    except Exception as e:
        print(f"Error writing battery percentage: {e}")

#############################
# QThread Worker           #
#############################

class Worker(QObject):
    finished = pyqtSignal()
    trayMessage = pyqtSignal(int, float, float)  # (icon_index, voltage, percentage)
    logMessage = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Initialize our INA219 with proper config
        self.ina = INA219(
            address=I2C_ADDRESS,
            i2c_bus=I2C_BUS,
            shunt_ohms=SHUNT_OHMS,
            max_expected_amps=MAX_CURRENT
        )

    def run(self):
        global mustHalt, mutex
        while True:
            # Check if we should halt
            mutex.lock()
            if mustHalt:
                mutex.unlock()
                break
            mutex.unlock()

            # Read voltage from INA219
            bus_voltage = self.ina.read_bus_voltage()
            if bus_voltage is not None:
                # Convert to a "battery %" from MIN_VOLTAGE..MAX_VOLTAGE
                percentage = (bus_voltage - MIN_VOLTAGE) / (MAX_VOLTAGE - MIN_VOLTAGE) * 100
                percentage = max(0, min(100, percentage))

                # Figure out which icon to use (0..7 for empty->full, etc.)
                icon_index = self.pick_icon(percentage)

                # Emit to update tray
                self.trayMessage.emit(icon_index, bus_voltage, percentage)

                # Optionally write battery % to sysfs/fallback
                write_battery_percentage(percentage)
            else:
                # reading error => show alert icon
                self.trayMessage.emit(9, 0.0, 0.0)
                self.logMessage.emit("INA219 read error")

            time.sleep(POLL_INTERVAL)

        self.finished.emit()

    def pick_icon(self, percentage):
        """
        Return an integer index [0..7,9,...] corresponding to battery icons.
        Feel free to map these to your own icon sets more precisely.
        """
        # Example approach: each 14% step up to 100
        if percentage <= 5:
            return 0
        elif percentage < 15:
            return 0
        elif percentage < 30:
            return 1
        elif percentage < 45:
            return 2
        elif percentage < 60:
            return 3
        elif percentage < 75:
            return 4
        elif percentage < 85:
            return 5
        elif percentage < 95:
            return 6
        else:
            return 7  # "full"

#############################
# Main Application / Tray  #
#############################

mustHalt = False
mutex = QMutex()

def halt():
    global mustHalt
    global mutex
    mutex.lock()
    mustHalt = True
    mutex.unlock()

def message(msg):
    logging.info(str(msg))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Provide your icons (ensure these files exist or update paths)
    icons = [
        QIcon("battery_0.png"),        # 0: very low
        QIcon("battery_1.png"),        # 1
        QIcon("battery_2.png"),        # 2
        QIcon("battery_3.png"),        # 3
        QIcon("battery_4.png"),        # 4
        QIcon("battery_5.png"),        # 5
        QIcon("battery_6.png"),        # 6
        QIcon("battery_7.png"),        # 7: full
        QIcon("battery_charging.png"), # 8 (not used unless you add charging logic)
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
    tray.setIcon(icons[10])  # start "unknown"
    tray.setVisible(True)

    # Function that updates the tray icon & tooltip
    def changeBatteryStatus(icon_index, voltage, percentage):
        tray.setIcon(icons[icon_index])
        s = f"{percentage:.1f}% ({voltage:.2f}V)"
        tray.setToolTip(s)

        localTime = time.localtime(time.time())
        logging.info(
            f"{localTime.tm_year:04d}-{localTime.tm_mon:02d}-{localTime.tm_mday:02d} "
            f"{localTime.tm_hour:02d}:{localTime.tm_min:02d}:{localTime.tm_sec:02d} "
            f"Icon: {icon_index} ({iconnames[icon_index]}) => {s}"
        )

    # QThread usage
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

    # Start the thread
    thread.start()

    sys.exit(app.exec_())

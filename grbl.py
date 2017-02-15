#

"""GRBL Interface for X-Carve -- Library"""

import argparse
import logging
import os
import re
import serial
import sys
import time

'''
DESIGN NOTES:
  * This is a library, the MAIN is just for testing
  *
'''

DEBUG_MODE = True

GRBL_VERSION = "1.0cJDN-2"

GRBL_PROMPT = "Grbl {0} ['$' for help]".format(GRBL_VERSION)

DEF_SERIAL_DEV = "COM3"

GRBL_RX_BUFFER_SIZE = 128

# GRBL Serial Settings: 115200, 8-N-1
DEF_SERIAL_SPEED = 115200
DEF_SERIAL_TIMEOUT = 0.1    # serial port timeout (secs)
DEF_SERIAL_DELAY = 0.1      # inter-character TX delay (secs)

DEF_STARTUP_CMDS = ["$H", "G21", "G90"]    # home, mm, absolute mode

#### N.B. This applies to release 0.9 and above

# Command groups
NON_MODAL_CMDS = 0
MOTION_MODES = 1
FEED_MODES = 2
UNIT_MODES = 3
DISTANCE_MODES = 4
ARC_MODES = 5
PLANE_MODES = 6
TOOL_LENGTH_MODES = 7
CUTTER_MODES = 8
COORDINATE_MODES = 9
CONTROL_MODES = 10
PROGRAM_FLOW = 11
COOLANT_CONTROL = 12
SPINDLE_CONTROL = 13
NON_CMD_WORDS = 14

# List of supported G-Codes in V1.1
# N.B. M30 and M7 ????
GCODES = {
    'NON_MODAL_CMDS': (["G4", "G10L2", "G10L20", "G28", "G30", "G28.1",
                       "G30.1", "G53", "G92", "G92.1"],
                       "Non-Modal Commands"),
    'MOTION_MODES': (["G0", "G1", "G2", "G3", "G38.2", "G38.3", "G38.4",
                     "G38.5", "G80"],
                     "Motion Modes"),
    'FEED_MODES': (["G93", "G94"],
                   "Feed Rate Modes"),
    'UNIT_MODES': (["G20", "G21"],
                   "Unit Modes"),
    'DISTANCE_MODES': (["G90", "G91"],
                       "Distance Modes"),
    'ARC_MODES': (["G91.1"],
                  "Arc IJK Distance Modes"),
    'PLANE_MODES': (["G17", "G18", "G19"],
                    "Plane Select Modes"),
    'TOOL_LENGTH_MODES': (["G43.1", "G49"],
                          "Tool Length Offset Modes"),
    'CUTTER_MODES': (["G40"],
                     "Cutter Compensation Modes"),
    'COORDINATE_MODES': (["G54", "G55", "G56", "G57", "G58", "G59"],
                         "Coordinate System Modes"),
    'CONTROL_MODES': (["G61"],
                      "Control Modes"),
    'PROGRAM_FLOW': (["M0", "M1", "M2", "M30"],
                     "Program Flow"),
    'COOLANT_CONTROL': (["M7", "M8", "M9"],
                        "Coolant Control"),
    'SPINDLE_CONTROL': (["M3", "M4", "M5"],
                        "Spindle Control"),
    'NON_CMD_WORDS': (["F", "I", "J", "K", "L", "N", "P", "R", "S", "T", "X",
                       "Y", "Z"],
                      "Valid Non-Command Words")
}

# '$' returns help the '$' and enter are not echoed
# '[0-132]=value' to save Grbl setting value
# 'N[0-9]=line' to save startup block

DLR_VIEW_SETTINGS = '$'
DLR_VIEW_PARAMETERS = '#'
DLR_VIEW_PARSER = 'G'
DLR_VIEW_BUILD = 'I'
DLR_VIEW_STARTUPS = 'N'
DLR_GCODE_MODE = 'C'
DLR_KILL_ALARM = 'X'
DLR_RUN_HOMING = 'H'

DOLLAR_CMDS = {
    DLR_VIEW_SETTINGS: "view Grbl settings",
    DLR_VIEW_PARAMETERS: "view # parameters",
    DLR_VIEW_PARSER: "view parser state",
    DLR_VIEW_BUILD: "view build info",
    DLR_VIEW_STARTUPS: "view startup blocks",
    DLR_GCODE_MODE: "check gcode mode",
    DLR_KILL_ALARM: "kill alarm lock",
    DLR_RUN_HOMING: "run homing cycle"
}

# Realtime commands can be issued at any time
RT_CYCLE_START = '~'
RT_FEED_HOLD = '!'
RT_CURRENT_STATUS = '?'
RT_RESET_GRBL = '\u0003'

REALTIME_CMDS = {
    RT_CYCLE_START: "cycle start",
    RT_FEED_HOLD: "feed hold",
    RT_CURRENT_STATUS: "current status",
    RT_RESET_GRBL: "reset Grbl"      # Ctrl-X
}

GS_DEFAULT = 0
GS_DESCRIPTION = 1
GS_UNITS = 2
GS_TYPE = 3

#### FIXME update with my default values
GRBL_SETTINGS = {
    0: (10, "step pulse", "usec", int),
    1: (25, "step idle delay", "msec", int),
    2: (0, "step port invert", "bitmask", int),
    3: (6, "dir port invert", "bitmask", int),
    4: (0, "step enable invert", "boolean", bool),
    5: (0, "limit pins invert", "boolean", bool),
    6: (0, "probe pin invert", "boolean", bool),
    10: (3, "status report", "bitmask", int),
    11: (0.020, "junction deviation", "mm", float),
    12: (0.002, "arc tolerance", "mm", float),
    13: (0, "report inches", "bool", ),
    20: (0, "soft limits", "bool"),
    21: (0, "hard limits", "bool"),
    22: (0, "homing cycle", "bool"),
    23: (1, "homing dir invert", "bitmask"),
    24: (50.000, "homing feed", "mm/min"),
    25: (635.000, "homing seek", "mm/min"),
    26: (250, "homing debounce", "msec"),
    27: (1.000, "homing pull-off", "mm"),
    100: (314.961, "x", "step/mm"),
    101: (314.961, "y", "step/mm"),
    102: (314.961, "z", "step/mm"),
    110: (635.000, "x max rate", "mm/min"),
    111: (635.000, "y max rate", "mm/min"),
    112: (635.000, "z max rate", "mm/min"),
    120: (50.000, "x accel", "mm/sec^2"),
    121: (50.000, "y accel", "mm/sec^2"),
    122: (50.000, "z accel", "mm/sec^2"),
    130: (225.000, "x max travel", "mm"),
    131: (125.000, "y max travel", "mm"),
    132: (170.000, "z max travel", "mm")
}


class SerialDevice(object):
    def __init__(self, serialDev, speed=DEF_SERIAL_SPEED,
                 delay=DEF_SERIAL_DELAY, timeout=DEF_SERIAL_TIMEOUT):
        """
        Open serial port at given speed and send CRLF/CRLF to wake up GRBL

        @param serialDev ?
        @param speed ?
        @param delay ?
        @param timeout ?
        """
        self.speed = speed
        self.delay = delay
        self.dev = serial.Serial(serialDev, speed, timeout=timeout)

    def __del__(self):
        if self.dev.isOpen():
            self.dev.close()

    def sendLine(self, line):
        """
        Take string and send it to the device.

        @param line String that is a single command line (e.g., GCODE)

        Strip leading/trailing whitespace from the line, add a "\n" to the end
        line, wait for "delay" msecs for a response from the device.
        Return the response (or "" if none received within the delay time).
        """
        self.sendLineRaw(line)
        time.sleep(self.delay)
        out = ""
        while self.dev.inWaiting() > 0:
            out += self.dev.readline()
            time.sleep(self.delay)
        return out.strip()

    def sendLineRaw(self, line):
        """
        Take string and send it to the device.

        @param line String that is a single command line (e.g., GCODE)

        Strip the given line and add a "\n" to the end of it.
        """
        self.dev.write(line.strip() + "\n")


class GrblDevice(SerialDevice):
    def __init__(self, serialDev, startupCmds=DEF_STARTUP_CMDS,
                 speed=DEF_SERIAL_SPEED, delay=DEF_SERIAL_DELAY):
        super(GrblDevice, self).__init__(serialDev, speed, delay)

        # wake up the GRBL device and wait for it to respond
        logging.debug("Initialize GRBL on %s, at %d baud", serialDev, speed)
        self.dev.write("\r\n\r\n")
        time.sleep(1.0)         # wait for the Arduino to wake up
        self.dev.flushInput()

        # get the GRBL settings
        resp = self.sendLine("$")
        self.settings = GrblDevice._parseGrblSettings(resp)

        # issue the startup commands
        for line in startupCmds:
            resp = self.sendLine(line)

    @staticmethod
    def _getSettingsVal(settingNum):
        return GRBL_SETTINGS[settingNum][GS_TYPE]

    @staticmethod
    def _parseGrblSettings(lines):
        settings = {}
        pattern = re.compile("^\$([0-9]+)=(.*) ")
        for line in lines:
            match = pattern.match(line)
            num = int(match.group(1))
            val = GrblDevice._getSettingVal(num, (match.group(2)))
            settings[num] = val
        return settings

    def getSettings(self):
        return self.settings

    def sendCycleStart(self):
        self.dev.write(RT_CYCLE_START)
        self.dev.flush()

    def sendFeedHold(self):
        self.dev.write(RT_FEED_HOLD)
        self.dev.flush()

    def sendGetCurrentStatus(self):
        self.dev.write(RT_CURRENT_STATUS)
        self.dev.flush()

    def sendResetGrbl(self):
        self.dev.write(RT_RESET_GRBL)
        self.dev.flush()

    def writeSettings(self, settings):
        for line in settings:
            # must use this method to write settings because writing to the
            #  EEPROM on the Arduino disables interrupts
            resp = self.sendLine(line)
            # TODO look at the response and deal with it

    def writeGcodes(self, gcodes):
        responses = []
        lineLengths = []
        for line in gcodes:
            line = line.strip()
            lineLengths.append(len(line) + 1)   # sendLine appends '\n' char
            while ((sum(lineLengths) >= (GRBL_RX_BUFFER_SIZE - 1)) or
                   self.dev.inWaiting()):
                resp = self.dev.readline().strip()
                if resp.find("ok") < 0 and resp.find("error") < 0:
                    logging.error("Unknown GRBL response: %s", resp)
                else:
                    responses.append(resp)
                    del lineLengths[0]
            resp = self.sendLine(line)
            responses.append(resp)
        logging.debug("Write GCODE responses: %s", responses)


#
# TEST
#
if __name__ == '__main__':
    usage = sys.argv[0] + "[-v] [-C <confFile>] [-d <serialDevice>]"
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '-v', '--verbose', action='count', default=0,
        help="increase verbosity")
    ap.add_argument(
        '-C', '--configFile', action='store',
        help="configuration input file (overridden by command-line args)")
    ap.add_argument(
        '-d', '--device', action='store',
        help="path to serial device")
    options = ap.parse_args()

#    logging.basicConf(level=logging.DEBUG)
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    #### TODO make it look for a default config file if one isn't given
    if options.configFile:
        if not os.path.isfile(options.configFile):
            sys.stderr.write("Error: config file not found\n")
            sys.exit(1)
        with open(options.configFile, 'r') as ymlFile:
            confFile = yaml.load(ymlFile)
        dictMerge(config, confFile)

    TMP_FILE = "/tmp/grbl.txt"

    if options.verbose:
        sys.stdout.write("    Serial Device:  {0}\n".format(options.device))
        sys.stdout.write("\n")

    grbl = GrblDevice(options.device)

    grbl.sendResetGrbl()

    gcodes = ["G1", "G2", "G3"]
    grbl.writeGcodes(gcodes)

    print "DONE"

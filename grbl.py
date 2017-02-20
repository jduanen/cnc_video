"""X-Carve GRBL Device Interface -- Library"""

import argparse
import logging
import re
import serial
import sys
import time
from Queue import Queue

from util import Alarm, typeCast


'''
DESIGN NOTES:
  * This is a library, the MAIN is just for testing
  *
'''

#### TODO make commands gather all responses and do delays by default -- DRY

DEBUG_MODE = True

GRBL_VERSION = "1.0cJDN-2"

GRBL_PROMPT = "Grbl {0} ['$' for help]".format(GRBL_VERSION)

GRBL_RX_BUFFER_SIZE = 128


#### FIXME make these be part of the config, and pass the config to the constructor
#### Also, add any (optional) functions we might want to run at startup

DEF_SERIAL_DEV = "COM3"

# GRBL Serial Settings: 115200, 8-N-1
DEF_SERIAL_SPEED = 115200
DEF_SERIAL_TIMEOUT = 0.1    # serial port timeout (secs)
DEF_SERIAL_DELAY = 0.1      # inter-character TX delay (secs)

DEF_STARTUP_CMDS = ["$H", "G21", "G90"]    # home, mm, absolute mode
DEF_STARTUP_CMDS = [] #### TMP TMP TMP


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
    13: (0, "report inches", "boolean", bool),
    20: (0, "soft limits", "boolean", bool),
    21: (0, "hard limits", "boolean", bool),
    22: (0, "homing cycle", "boolean", bool),
    23: (1, "homing dir invert", "bitmask", int),
    24: (50.000, "homing feed", "mm/min", float),
    25: (635.000, "homing seek", "mm/min", float),
    26: (250, "homing debounce", "msec", int),
    27: (1.000, "homing pull-off", "mm", float),
    30: (1.0, "RPM max", "rpm", float),
    31: (0.0, "RPM min", "rpm", float),
    100: (314.961, "x", "step/mm", float),
    101: (314.961, "y", "step/mm", float),
    102: (314.961, "z", "step/mm", float),
    110: (635.000, "x max rate", "mm/min", float),
    111: (635.000, "y max rate", "mm/min", float),
    112: (635.000, "z max rate", "mm/min", float),
    120: (50.000, "x accel", "mm/sec^2", float),
    121: (50.000, "y accel", "mm/sec^2", float),
    122: (50.000, "z accel", "mm/sec^2", float),
    130: (225.000, "x max travel", "mm", float),
    131: (125.000, "y max travel", "mm", float),
    132: (170.000, "z max travel", "mm", float)
}


class SerialDevice(object):
    def __init__(self, serialDev, speed=DEF_SERIAL_SPEED,
                 delay=DEF_SERIAL_DELAY, timeout=DEF_SERIAL_TIMEOUT):
        """
        Open serial port at given speed and send CRLF/CRLF to wake up GRBL

        @param serialDev ?
        @param speed ?
        @param delay ?
        @param timeout How long to wait for CR on readline() (in msec)
        """
        self.speed = speed
        self.delay = delay
        self.dev = None
        try:
            self.dev = serial.Serial(serialDev, speed, timeout=timeout)
        except:
            logging.error("Failed to open serial device '%s'", serialDev)
            raise RuntimeError

    def __del__(self):
        if self.dev:
            if self.dev.isOpen():
                self.dev.close()

    def sendLine(self, line, delay):
        """
        Take string and send it to the device.

        @param line String that is a single command line (e.g., GCODE)

        Strip leading/trailing whitespace from the line, add a "\n" to the end
        line, wait for "delay" msecs for a response from the device.
        Return the response (or "" if none received within the delay time).
        """
        self.sendLineRaw(line)
        time.sleep(delay)
        return self.getResponse()

    def sendLineRaw(self, line):
        """
        Take string and send it to the device.

        @param line String that is a single command line (e.g., GCODE)

        Strip the given line and add a "\n" to the end of it.
        """
        self.dev.write(line.strip() + "\n")

    def getResponse(self):
        """
        Get an immediate response line from the GRBL device.

        Reads a single response line from the GRBL device.
        A response line ends with a '\n' (by default).
        This will build up the line from characters if necessary, but it will
         only return the first response line that it finds.
        The returned line is stripped of (leading and trailing) whitespace.
        If no response is available, then this returns a None.
        """
        out = ""
        while self.dev.inWaiting() > 0:
            resp = self.dev.readline()
            sys.stdout.flush()
            if resp.endswith("\n"):
                # got the end of the line, so return it
                out += resp
                break
            else:
                if len(resp):
                    # got chars, but not at the end, so accumulate them
                    out += resp
            time.sleep(0.1)
        if out == "":
            return None
        return out.strip()

    def waitForResponse(self, timeout):
        """
        Wait for up to 'timeout' seconds for a response line.

        Returns the next response line from the device that is sent before the
         timeout expires.
        Returns a None if no response is forthcoming before the timeout.
        """
        q = Queue()
        alarm = Alarm(q, timeout)
        alarm.start()
        r = self.getResponse()
        while r is None:
            if not q.empty():
                logging.info("Timed out waiting for response")
                return None
            r = self.getResponse()
        del alarm
        return r

    def gatherResponses(self, timeout):
        """
        Return a list of response lines from the device.

        Gather up all the response lines from the device until no more are
         available for 'timeout' secs.
        Returns an empty list if no response lines received before the timeout.
        """
        resps = []
        r = self.waitForResponse(timeout)
        while r is not None:
            resps.append(r)
            r = self.waitForResponse(timeout)
        return resps


class GrblDevice(SerialDevice):
    def __init__(self, serialDev, startupCmds=DEF_STARTUP_CMDS,
                 speed=DEF_SERIAL_SPEED, delay=DEF_SERIAL_DELAY):
        super(GrblDevice, self).__init__(serialDev, speed, delay)

        # wake up the GRBL device and wait for it to respond
        logging.debug("Initialize GRBL on %s, at %d baud", serialDev, speed)
        self.dev.write("\r\n\r\n")
        time.sleep(1.0)                   # wait for the Arduino to wake up
        resp = self.gatherResponses(1.0)  # discard noise
        logging.debug("GRBL device startup response: %s", resp)

        # reset the GRBL device
        resp = self.resetGrbl()
        if resp is None:
            logging.error("No response from GRBL device to reset command")
            raise RuntimeError

        # kill any machine alarms
        resp = self.killAlarm()
        if resp is None:
            logging.error("Kill Alarm command failed")
            raise RuntimeError

        # get the GRBL settings
        resp = self.getSettings()
        if resp is None:
            logging.error("Failed to get GRBL device settings")
            raise RuntimeError

        # issue the startup commands
        for line in startupCmds:
            resp = self.sendLine(line, self.delay)
            #### TODO Do something with the response

    @staticmethod
    def _parseGrblSettings(lines):
        if not lines or len(lines) < 1:
            return None
        settings = {}
        pattern = re.compile("^\$([0-9]+)=([^ ]*) .*$")
        for line in lines:
            m = pattern.match(line)
            if m is None:
                continue
            num = int(m.group(1))
            typ = GRBL_SETTINGS[num][GS_TYPE]
            val = typ(m.group(2))
            if val is None:
                logging.error("Invalid setting value")
                return None
            settings[num] = val
        return settings

    def sendDollarCmd(self, cmd):
        if cmd not in DOLLAR_CMDS.keys():
            logging.error("Invalid $ Command: '%s'", cmd)
            return None
        return self.sendLine("$" + cmd, self.delay)

    def killAlarm(self):
        return self.sendDollarCmd(DLR_KILL_ALARM)

    def runHomingCycle(self):
        return self.sendDollarCmd(DLR_RUN_HOMING)

    def getSettings(self):
        resps = []
        r = self.sendDollarCmd(DLR_VIEW_SETTINGS)
        if r:
            resps.append(r)
        r = self.gatherResponses(3.0)
        if r:
            resps += r
        if len(resps) < 1:
            return None
        if resps[-1].startswith("ok"):
            del resps[-1]
        self.settings = GrblDevice._parseGrblSettings(resps)
        if not self.settings:
            logging.debug("Unable to get settings from device")
            return None
        return self.settings

    def getGcodeMode(self):
        return self.sendDollarCmd(DLR_GCODE_MODE)

    def getStartupCmds(self):
        return self.sendDollarCmd(DLR_VIEW_STARTUPS)

    def getBuildInfo(self):
        r = self.sendDollarCmd(DLR_VIEW_BUILD)
        if r:
            return r[1:-2]
        else:
            logging.error("Unable to get GRBL build info")
            return None

    def getGcodeParserInfo(self):
        return self.sendDollarCmd(DLR_VIEW_PARSER)

    def getParameters(self):
        return self.sendDollarCmd(DLR_VIEW_PARAMETERS)

    def getCurrentStatus(self):
        self.dev.write(RT_CURRENT_STATUS)
        self.dev.flush()
        time.sleep(self.delay)
        return self.getResponse()

    def cycleStart(self):
        self.dev.write(RT_CYCLE_START)
        self.dev.flush()
        time.sleep(self.delay)
        return self.getResponse()

    def feedHold(self):
        self.dev.write(RT_FEED_HOLD)
        self.dev.flush()
        time.sleep(self.delay)
        return self.getResponse()

    def resetGrbl(self):
        self.dev.write(RT_RESET_GRBL)
        self.dev.flush()
        time.sleep(1.0)
        return self.gatherResponses(1.0)

    def writeSettings(self, settings):
        for line in settings:
            # must use this method to write settings because writing to the
            #  EEPROM on the Arduino disables interrupts
            resp = self.sendLine(line, self.delay)
            logging.debug("Send line response: %s", resp)
            # FIXME fix return values

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
            resp = self.sendLine(line, self.delay)
            responses.append(resp)
        logging.debug("Write GCODE responses: %s", responses)
        #### FIXME fix return values

    def printSettings(self):
        sys.stdout.write("Settings:\n")
        for num in sorted(self.settings.keys()):
            sys.stdout.write("    ${0}: {1} ({2}, {3})\n".
                             format(num, self.settings[num],
                                    GRBL_SETTINGS[num][GS_DESCRIPTION],
                                    GRBL_SETTINGS[num][GS_UNITS]))


#
# TEST
#
if __name__ == '__main__':
    import json

    usage = sys.argv[0] + "[-v] [-d <serialDevice>]"
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '-v', '--verbose', action='count', default=0,
        help="increase verbosity")
    ap.add_argument(
        '-d', '--device', action='store',
        help="path to serial device")
    options = ap.parse_args()

    logger = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    if options.verbose:
        sys.stdout.write("    Serial Device:  {0}\n".format(options.device))
        sys.stdout.write("\n")

    """
    s = SerialDevice(options.device)
    s.sendLineRaw("\r\n\r\n")
    time.sleep(2.0)         # wait for the Arduino to wake up
    rs = s.gatherResponses(0.1)
    print "R0: ", rs
    sys.stdout.flush()

    r = s.sendLine(RT_RESET_GRBL, 3.0)
    print "R1: ", r
    sys.stdout.flush()
    rs = s.gatherResponses(10.0)
    print "RS: ", rs
    sys.stdout.flush()
#    while r != "\r\n":
    time.sleep(3)
    r = s.getResponse()
    print("R2: ", r)
    """

    grbl = GrblDevice(options.device)

    """
    settings = grbl.getSettings()
    print("Settings:")
    json.dump(settings, sys.stdout, indent=4, sort_keys=True)
    print ""
    """
    #grbl.printSettings()

    status = grbl.getCurrentStatus()
    print "STATUS:", status

    info = grbl.getBuildInfo()
    print "BUILD INFO:", info

    parms = grbl.getParameters()
    print "PARAMETERS:", parms

    #grbl.runHomingCycle()

    #gcodes = ["$H", "G21", "G90"]    # home, mm, absolute mode
    #r = grbl.writeGcodes(gcodes)
    #print "RESULT:", r

    print("DONE")

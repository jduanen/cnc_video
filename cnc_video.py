#!/cygdrive/c/Python27/python
####!/usr/bin/env python

"""X-Carve Microscope Tool"""

import argparse
import collections
import os
import signal
import sys
import yaml

import cv2

import vid


####
#
# Left mouse click shows distances to the clicked point, and left mouse with
#  the Shift key selects the nearest feature (of the current type of feature --
#  e.g., line, corner, circle/arc)
#
####

'''
TODO:
 * alignment functions
 * calibration functions
   - geometric correction
   - pixel to mm conversion
 * feature type mode selection
 * feature detection

 * add feature selector:
   - Edge
     * horizontal
     * vertical
   - Corner
     * upper/lower
     * left/right
   - Circle
     * center
     * tangent (pt to line)
       - top/bottom/left/right
   - Point to Line
 * Add text:
   - Angle
   - Distance
     * X
     * Y

 * Connect with GRBL (closed loop):
   - auto-focus (Z-axis only, stay within range, maximize sharpness)
   - validate return to home (apply target decal to wasteboard)
   - calculate camera offset (X & Y distance to hole center, use hint and
     find drill hole center)

 * Make calibration mode where fixed size object is placed on work and pixels
   to mm conversion is calculated (use ruler)

 * Show distance to selected/nearest feature -- e.g., corner, center of
   circle), and show angle of selected lines

 * Select feature mode (e.g., edge, corner, or circle) (and submode --
   e.g., tangent t/b/l/r, center, H/V, etc.) and highlight matching features
   allow mouse-click selection and then measure/display distances (in pixels)
   to H, to V, and to origin (as well as angles?)

 * Add display of feature type selection mode?

 * Fix seg-fault/core dump on exit

 * Allow optional camera adjustment inputs (e.g., contrast, exposure, etc.)
'''

DEBUG_MODE = False

DEF_VIDEO_DEVICE = 0
DEF_CROSSHAIR_THICKNESS = 1
DEF_CROSSHAIR_ALPHA = 0.5
##DEF_CROSSHAIR_COLOR = (255, 255, 0)  # cyan
##DEF_CROSSHAIR_COLOR = (255, 0, 255)  # magenta
DEF_CROSSHAIR_COLOR = (0, 255, 255)  # yellow
DEF_HIGHLIGHT_COLOR = (0, 255, 0)    # green
DEF_VIDEO_SIZE = (800, 600)

DEF_FONT_COLOR = (255, 0, 0)    # blue
DEF_FONT_FACE = vid.FONT_FACE_1 if (DEF_VIDEO_SIZE[0] < 512) else vid.FONT_FACE_0

#### TODO calculate good defaults for fontScale and fontThickness based on default video height
DEF_FONT_SCALE = 1
DEF_FONT_THICKNESS = 1 if (DEF_FONT_FACE == vid.FONT_FACE_1) else 2


# Initialize configuration with default values here
# N.B. These get overridden by config file values, which are then overriden by
#  command-line inputs.
config = {
    'device': DEF_VIDEO_DEVICE,                 # camera device name (string)
    'size': DEF_VIDEO_SIZE,                     # image width/height (tuple)
    'adjustments': False,                       # Enable/disable realtime input
    'crosshair': {
        'enable': False,                        # Enable/disable (boolean)
        'color': DEF_CROSSHAIR_COLOR,           # Color for normal (tuple)
        'thickness': DEF_CROSSHAIR_THICKNESS,   # Thickness (pixels)
        'alpha': DEF_CROSSHAIR_ALPHA,           # Alpha value (float)
        'highlightColor': DEF_HIGHLIGHT_COLOR   # Color for highlighted (tuple)
    },
    'osd': {
        'enable': True,                         # Enable/disable OSD (boolean)
        'color': DEF_FONT_COLOR,                # Color (tuple)
        'face': DEF_FONT_FACE,                  # Font face (string)
        'scale': DEF_FONT_SCALE,                # Font scale (int)
        'thickness': DEF_FONT_THICKNESS         # Font weight (int)
    }
}


# Keyboard input handler
class KeyboardInput(object):
    H_EDGE, V_EDGE, CORNER, CIRCLE = range(4)
    FEATURES = ["H Edge", "V Edge", "Corner", "Circle"]

    def __init__(self):
        self.mode = None
        self.handlers = {ord('h'): self._hEdge,
                         ord('v'): self._vEdge,
                         ord('c'): self._corner,
                         ord('r'): self._circle,
                         27: self._reset}

    def input(self):
        # wait up to 1ms to get a char from the keyboard
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return False
        if key in self.handlers:
            self.handlers[key]()
        return True

    # select Horizontal Edge feature mode
    def _hEdge(self):
        self.mode = KeyboardInput.H_EDGE

    # select Vertical Edge feature mode
    def _vEdge(self):
        self.mode = KeyboardInput.V_EDGE

    # select Corner feature mode
    def _corner(self):
        self.mode = KeyboardInput.CORNER

    # select Circle feature mode
    def _circle(self):
        self.mode = KeyboardInput.CIRCLE

    # reset feature mode
    def _reset(self):
        self.mode = None


# Dummy callback (used in trackbars)
def nullHandler(*arg):
    pass


# Generic signal handler
def sigHandler(signum, frame):
    sys.stderr.write("Signal caught: {0}\n".format(signum))
    sys.exit(1)


# Merge a new dict into an old one, updating the old one (recursively).
def dictMerge(old, new):
    for k, v in new.iteritems():
        if (k in old and isinstance(old[k], dict) and
            isinstance(new[k], collections.Mapping)):
            dictMerge(old[k], new[k])
        else:
            old[k] = new[k]


# Take the delta X, delta Y, and dist measurements, and overlay them at the
#  given location on the given image.
# Return the image with the overlay.
# Positions: "TL"=top left, "TR"=top right, "BL"=bottom left, "BR"=bottom right
def drawMeasurements(img, osd, pos, dx, dy, dist):
    if dx is not None:
        img = osd.overlay(img, pos, 0, "X: {0}mm".format(round(dx, 2)))
    if dy is not None:
        img = osd.overlay(img, pos, 1, "Y: {0}mm".format(round(dy, 2)))
    if dist is not None:
        img = osd.overlay(img, pos, 2, "D: {0}mm".format(round(dist, 2)))
    return img


#
# MAIN
#
def main():
    global config

    usage = sys.argv[0] + "[-v] [-x] [-o] [-d <devIndx>] [-A] [-s (<width>, <height>)]"
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '-F', '--font', action='store', type=int, help="font face (number)")
    ap.add_argument(
        '-A', '--adjustments', action='store_true', default=False,
        help="enable run-time adjustments")
    ap.add_argument(
        '-a', '--alpha', action='store', type=float,
        help="crosshair alpha")
    ap.add_argument(
        '-t', '--thickness', action='store', type=int,
        help="crosshair thickness")
    ap.add_argument(
        '-c', '--color', action='store', type=str,
        help="crosshair color list -- 'B,G,R'")
    ap.add_argument(
        '-d', '--deviceIndex', action='store', type=int,
        help="video input device index")
    ap.add_argument(
        '-s', '--size', action='store', type=str,
        help="video input frame size -- 'width,height'")
    ap.add_argument(
        '-x', '--crosshair', action='store_true',
        help="enable crosshair")
    ap.add_argument(
        '-o', '--osd', action='store_true',
        help="enable OSD overlay")
    ap.add_argument(
        '-v', '--verbose', action='count', default=0,
        help="increase verbosity")
    ap.add_argument(
        '-C', '--configFile', action='store',
        help="configuration input file (overridden by command-line args)")
    options = ap.parse_args()

    signal.signal(signal.SIGSEGV, sigHandler)

    #### TODO make it look for a default config file if one isn't given
    if options.configFile:
        if not os.path.isfile(options.configFile):
            sys.stderr.write("Error: config file not found\n")
            sys.exit(1)
        with open(options.configFile, 'r') as ymlFile:
            confFile = yaml.load(ymlFile)
        dictMerge(config, confFile)

    if options.deviceIndex:
        config['device'] = options.deviceIndex
    if options.size:
        config['size'] = [int(x) for x in options.size.split(",")]
    if options.adjustments:
        config['adjustments'] = options.adjustments
    if options.osd:
        config['osd']['enable'] = True
    if options.crosshair:
        config['crosshair']['enable'] = True
    if options.alpha:
        config['crosshair']['alpha'] = options.alpha
    if options.thickness:
        config['crosshair']['thickness'] = options.thickness
    if options.color:
        config['crosshair']['color'] = [int(x) for x in options.color.split(",")]
    if options.font:
        config['osd']['face'] = options.font

    # Aliases for OSD locations
    TL = vid.OnScreenDisplay.TOP_LEFT
    TR = vid.OnScreenDisplay.TOP_RIGHT
    BL = vid.OnScreenDisplay.BOTTOM_LEFT
    BR = vid.OnScreenDisplay.BOTTOM_RIGHT

    cv2.namedWindow('view')
    if config['adjustments']:
        if config['crosshair']['enable']:
            alpha = int(config['crosshair']['alpha'] * 100)
            cv2.createTrackbar('alpha', 'view', alpha, 100, nullHandler)
        cv2.createTrackbar('thrs1', 'view', 0, 10000, nullHandler)
        cv2.createTrackbar('thrs2', 'view', 0, 10000, nullHandler)
        blkSize = 5
        kernelSize = 5
        kVal = 5
        cv2.createTrackbar('blkSize', 'view', blkSize, 100, nullHandler)
        cv2.createTrackbar('kernelSize', 'view', kernelSize, 30, nullHandler)
        cv2.createTrackbar('kVal', 'view', kVal, 100, nullHandler)
    cap = cv2.VideoCapture(config['device'])

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config['size'][0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config['size'][1])

    vidWidth = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vidHeight = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vidRate = cap.get(cv2.CAP_PROP_FPS)
    vidFormat = cap.get(cv2.CAP_PROP_FOURCC)

    # update the config with the actual width/height of the image
    config['imgWidth'] = vidWidth
    config['imgHeight'] = vidHeight

    ch = config['crosshair']
    if ch['enable']:
        xhair = vid.Crosshair(vidWidth, vidHeight, ch, config['adjustments'])

    o = config['osd']
    if o['enable']:
        osd = vid.OnScreenDisplay(config)
    else:
        osd = None

    if options.verbose:
        sys.stdout.write("    Video Device Index:  {0}\n".
                         format(config['device']))
        sys.stdout.write("    Video Dimensions:    {0} x {1}\n".
                         format(vidWidth, vidHeight))
        sys.stdout.write("    Video Frame Rate:    {0}\n".format(vidRate))
        sys.stdout.write("    Video Format:        {0}\n".format(vidFormat))
        sys.stdout.write("    On-Screen Display:   ")
        if o['enable']:
            sys.stdout.write("Enabled\n")
            sys.stdout.write("        Font Face:           {0}\n".
                             format(o['face']))
            sys.stdout.write("        Font Scale:          {0}\n".
                             format(o['scale']))
            sys.stdout.write("        Font Color:          {0}\n".
                             format(o['color']))
            sys.stdout.write("        Font Thickness:      {0}\n".
                             format(o['thickness']))
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("    Crosshair Display:   ")
        if ch['enable']:
            sys.stdout.write("Enabled\n")
            sys.stdout.write("        Thickness:           {0}\n".
                             format(ch['thickness']))
            sys.stdout.write("        Color:               {0}\n".
                             format(ch['color']))
            sys.stdout.write("        Alpha:               {0}\n".
                             format(ch['alpha']))
            sys.stdout.write("        Highlight Color:     {0}\n".
                             format(ch['highlightColor']))
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("    Realtime Controls ")
        if config['adjustments']:
            sys.stdout.write("Enabled\n")
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("\n")
        sys.stdout.flush()

    vidProc = vid.VideoProcessing()
    kbd = KeyboardInput()

    #### TODO get calibration data
    cal = None
    measure = vid.Measurement(vidWidth, vidHeight, cal)

    def clickHandler(event, x, y, flags, param):
        if flags & cv2.EVENT_LBUTTONDOWN:
            if flags & cv2.EVENT_FLAG_SHIFTKEY:
                # select the feature nearest to the click
                x, y = vidProc.getNearestFeature(x, y)
            measure.setValues(x, y)

    cv2.setMouseCallback('view', clickHandler)

    run = True
    while (run):
        # capture a frame of video from the camera
        ret, img = cap.read()

        # process video frame, adding any overlays, and return the new frame
        img = vidProc.processFrame(img)
        if ch['enable']:
            img = xhair.overlay(img)
        if o['enable']:
            dX, dY, dist = measure.getValues()
            img = drawMeasurements(img, osd, TL, dX, dY, dist)
            if kbd.mode is not None:
                text = "MODE: " + KeyboardInput.FEATURES[kbd.mode]
                img = osd.overlay(img, TR, 0, text)

        # display the processed and overlayed video frame
        cv2.imshow('view', img)

        # process keyboard input
        run = kbd.input()

    # clean up everything and exit
    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

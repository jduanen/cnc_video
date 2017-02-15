#!/cygdrive/c/Python27/python
####!/usr/bin/env python

"""X-Carve Microscope Tool"""

import argparse
import collections
import math
import os
import signal
import sys
import yaml

import numpy as np
import cv2


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

# "v4l2-ctl --list-formats-ext"
# 13mm camera:
#  * 0: YUYV 4:2:2 -- 640x480@30Hz, 800x600@20Hz, 1280x960@9Hz, 1600x1200@5Hz
#  * 1: MJPEG @ 30Hz -- 640x480, 800x600, 1280x960, 1600x1200

DEBUG_MODE = False

DEF_VIDEO_DEVICE = 0
DEF_CROSSHAIR_THICKNESS = 1
DEF_CROSSHAIR_ALPHA = 0.5
##DEF_CROSSHAIR_COLOR = (255, 255, 0)  # cyan
##DEF_CROSSHAIR_COLOR = (255, 0, 255)  # magenta
DEF_CROSSHAIR_COLOR = (0, 255, 255)  # yellow
DEF_HIGHLIGHT_COLOR = (0, 255, 0)    # green
DEF_VIDEO_SIZE = (800, 600)

MAX_CROSSHAIR_THICKNESS = 5
MAX_VIDEO_WIDTH = (4 * 1024)
MAX_VIDEO_HEIGHT = (2 * 1024)

# scale = 1, thickness = 1
FONT_FACE_0 = cv2.FONT_HERSHEY_SIMPLEX         # 27 close to fixed
FONT_FACE_1 = cv2.FONT_HERSHEY_PLAIN           # 15 small, fixed
FONT_FACE_2 = cv2.FONT_HERSHEY_DUPLEX          # 27 close to fixed
FONT_FACE_3 = cv2.FONT_HERSHEY_COMPLEX         # 27 light serif
FONT_FACE_4 = cv2.FONT_HERSHEY_TRIPLEX         # 27 heavy serif
FONT_FACE_5 = cv2.FONT_HERSHEY_COMPLEX_SMALL   # 19 small serif
FONT_FACE_6 = cv2.FONT_HERSHEY_SCRIPT_SIMPLEX  # 27 script-like
FONT_FACE_7 = cv2.FONT_HERSHEY_SCRIPT_COMPLEX  # 27 script-like

DEF_FONT_COLOR = (255, 0, 0)    # blue
DEF_FONT_FACE = FONT_FACE_1 if (DEF_VIDEO_SIZE[0] < 512) else FONT_FACE_0

#### TODO calculate good defaults for fontScale and fontThickness based on default video height
DEF_FONT_SCALE = 1
DEF_FONT_THICKNESS = 1 if (DEF_FONT_FACE == FONT_FACE_1) else 2


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


class Crosshair(object):
    """
    Crosshair to be alpha-blended over video.

    Horizontal and vertical parts can be (idependently) highlighted, e.g., to
     indicate alignment with selected feature.
    """
    def __init__(self, width, height, confVals, adjustments=False):
        """
        Instantiate Crosshair object.

        @param width Crosshair image width in pixels
        @param width Crosshair image height in pixels
        @param confVals See 'crosshair' field in config dict
        @param adjustments Enable real-time value adjustment inputs

        The given width and height must be the same as that of the video image.
        """
        self.hiH = False
        self.hiV = False
        self.width = width
        self.height = height
        self.color = confVals['color']
        self.thick = confVals['thickness']
        self.alpha = confVals['alpha']
        self.highlightColor = confVals['highlightColor']
        self.adjustments = adjustments
        if not self._validate():
            raise ValueError

    def _validate(self):
        if self.width < 0 or self.width > MAX_VIDEO_WIDTH:
            sys.stderr.write("Error: invalid crosshair image width\n")
            return False
        if self.height < 0 or self.height > MAX_VIDEO_HEIGHT:
            sys.stderr.write("Error: invalid crosshair image height\n")
            return False
        if self.thick < 1 or self.thick > MAX_CROSSHAIR_THICKNESS:
            sys.stderr.write("Error: invalid crosshair thickness\n")
            return False
        if ((len(self.color) != 3) or (min(self.color) < 0) or
                (max(self.color) > 255)):
            sys.stderr.write("Error: invalid crosshair color\n")
            return False
        if self.color == self.highlightColor:
            sys.stderr.write("Warning: crosshair and highlight colors are the same")
        if self.alpha < 0.0 or self.alpha > 1.0:
            sys.stderr.write("Error: invalid crosshair alpha\n")
            return False
        return True

    def _render(self, img, hiliteH=False, hiliteV=False):
        hStart = (0, (self.height / 2))
        hEnd = (self.width, (self.height / 2))
        vStart = ((self.width / 2), 0)
        vEnd = ((self.width / 2), self.height)

        if hiliteH:
            color = self.highlightColor
        else:
            color = self.color
        cv2.line(img, hStart, hEnd, color, self.thick)

        if hiliteV:
            color = self.highlightColor
        else:
            color = self.color
        cv2.line(img, vStart, vEnd, color, self.thick)
        return img

    def setHighlightH(self, val):
        """
        Turn highlight on/off for horizontal line of crosshair.

        @params val If True, highlight horizontal line of crossbar
        """
        if not isinstance(val, bool):
            raise ValueError
        self.hiH = val

    def setHighlightV(self, val):
        """
        Turn highlight on/off for vertical line of crosshair.

        @params val If True, highlight vertical line of crossbar
        """
        if not isinstance(val, bool):
            raise ValueError
        self.hiV = val

    def overlay(self, img):
        """
        Alpha-blend the crosshairs onto the (processed) video frame.

        @param img Image onto which crosshair is overlayed
        @returns Input image with crosshair overlayed
        """
        ovrly = self._render(img.copy(), self.hiH, self.hiV)
        if self.adjustments:
            self.alpha = (cv2.getTrackbarPos('alpha', 'view') / 100.0)
        cv2.addWeighted(ovrly, self.alpha, img, (1.0 - self.alpha), 0, img)
        return img


class OnScreenDisplay(object):
    """
    On-screen display ????
    <(optionally) put stuff in all four corners>
    """
    MAX_LINES = 3
    TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT = range(4)

    def __init__(self, confVals):
        """
        Instantiate OSD object.

        @param confVals See 'osd' field in config struct dict
        """
        self.fontFace = confVals['face']
        self.fontColor = confVals['color']
        self.fontScale = confVals['scale']
        self.fontThickness = confVals['thickness']

        #### FIXME make lineOrigins a 2D array for all 4 corners

        txtSize, baseline = cv2.getTextSize("M", self.fontFace, self.fontScale,
                                            self.fontThickness)
        self.txtHeight = txtSize[1]

        topOffset = 5
        lineSpacing = int(self.txtHeight / 3.0) + 3
        origin = (5, (topOffset + self.txtHeight))

        self.lineOrigins = [origin]

        for line in range(OnScreenDisplay.MAX_LINES - 1):
            nextY = origin[1] + ((self.txtHeight + lineSpacing) * (line + 1))
            self.lineOrigins.append((origin[0], nextY))
        print self.lineOrigins

    def overlay(self, img, corner, lineNum, text):
        """
        ????
        """
        if lineNum < 0 or lineNum >= OnScreenDisplay.MAX_LINES:
            raise ValueError
        bottomLeft = self.lineOrigins[corner][lineNum]
        if corner == OnScreenDisplay.TOP_LEFT:
            cv2.putText(img, text, bottomLeft, self.fontFace, self.fontScale,
                        self.fontColor, self.fontThickness, cv2.LINE_AA, False)
        elif corner == OnScreenDisplay.TOP_RIGHT:
            cv2.putText(img, text, bottomLeft, self.fontFace, self.fontScale,
                        self.fontColor, self.fontThickness, cv2.LINE_AA, False)
        elif corner == OnScreenDisplay.BOTTOM_LEFT:
            print "BL"
        elif corner == OnScreenDisplay.BOTTOM_RIGHT:
            print "BR"
        else:
            raise ValueError
        return img


class Measurement(object):
    def __init__(self, width, height, calData):
        self.deltaX = None    # distance to X axis in mm (float)
        self.deltaY = None    # distance to Y axis in mm (float)
        self.distance = None  # distance to origin in mm (float)

        self.width = width    # width of image in pixels (int)
        self.height = height  # height of image in pixels (int)

        self.originX = (width / 2)   # horiz center of image in pixels (int)
        self.originY = (height / 2)  # vertical center of image in pixels (int)

        self.calib = calData

    def getValues(self):
        return self.deltaX, self.deltaY, self.distance

    # take x/y in pixel coordinates and save distances
    def setValues(self, x, y):
        #### FIXME compute distances in mm (using calibration)
        self.deltaX = (x - self.originX)
        self.deltaY = (self.originY - y)
        self.distance = math.sqrt(self.deltaX**2 + self.deltaY**2)

    def getDeltaX(self):
        return self.deltaX

    def getDeltaY(self):
        return self.deltaY

    def getDistance(self):
        return self.distance


# Object that encapsulates all video processing to be done on the given
#  input video image stream.
class VideoProcessing(object):
    def __init__(self):
        pass

    def processFrame(self, img):
        #### TODO run img through camera calibration correction matrix

        #### Detection Pipeline:
        ####  * cvt2gray
        ####  * cvSmooth
        ####  * cvThreshold
        ####  * cvCanny
        ####  * cvFindContours
        ####  * cvApproxPoly

        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ####################
        # Line detection (with threshold sliders)
        if config['adjustments']:
            thrs1 = cv2.getTrackbarPos('thrs1', 'view')
            thrs2 = cv2.getTrackbarPos('thrs2', 'view')
        else:
            #### FIXME make these be reasonable values/variables
            thrs1 = 3000
            thrs2 = 4500
        edges = cv2.Canny(gray, thrs1, thrs2, apertureSize = 5)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 2, None, 30, 1)
        if lines is not None:
            for line in lines[0]:
                pt1 = (line[0], line[1])
                pt2 = (line[2], line[3])
                cv2.line(img, pt1, pt2, (0, 0, 255), 2)
        ###############
        # Corner detection
        gray = np.float32(gray)
        blkSize = cv2.getTrackbarPos('blkSize', 'view')
        kSize = (cv2.getTrackbarPos('kernelSize', 'view') | 1)
        k = (cv2.getTrackbarPos('kVal', 'view') / 100.0)
        dst = cv2.cornerHarris(gray, blkSize, kSize, k)
        #dst = cv2.cornerHarris(gray, 2, 3, 0.04)  # img, blockSize, ksize, k

        #result is dilated for marking the corners, not important
        dst = cv2.dilate(dst, None)

        # Threshold for an optimal value, it may vary depending on the image.
        img[dst > 0.01 * dst.max()] = [0, 0, 255]
        ###############
        # FAST detector
        # Initiate FAST object with default values
        fast = cv2.FastFeatureDetector_create()
        ####fast.setNonmaxSuppression(False)

        # find and draw the keypoints
        kp = fast.detect(img, None)
        cv2.drawKeypoints(img, kp, img, color=(255,0,0))
        ################
        cv2.goodFeaturesToTrack(blurred,                # img
                            500,                    # maxCorners
                            0.03,                   # qualityLevel
                            10,                     # minDistance
                            None,                   # corners, 
                            None,                   # mask, 
                            2,                      # blockSize, 
                            useHarrisDetector=True, # useHarrisDetector, 
                            k=0.04                  # k
                            )
        ###############
        cornerMap = cv.CreateMat(im.height, im.width, cv.CV_32FC1)
        cv.CornerHarris(imgray, cornerMap,3)
        for y in range(0, imgray.height):
            for x in range (0, imgray.width):
                harris = cv.Get2D(cornerMap, y, x)
                if harris[0] > 10e-06:
                    temp = cv.Circle(im, (x,y), 2, cv.RGB(115,0,25))
        ###############
        gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        gray = np.float32(gray)
        dst = cv2.cornerHarris(gray, 2, 3, 0.04)

        for y in range(0, gray.shape[0]):
            for x in range(0, gray.shape[1]):
                harris = cv2.Get2D(cv2.fromarray(dst), y, x) # get the x,y value
                # check the corner detector response
                if harris[0] > (0.01 * dst.max()):
                    print x,y # these are the locations of the matches
                    print 'Distance in pixels from origin: %d' % math.sqrt(x**2+y**2)
                    # draw a small circle on the original image
                    cv2.circle(img, (x,y), 2, (155, 0, 25))
        ###############

        corners = cv2.goodFeaturesToTrack(img, 4, 0.5, 10)
        """
        return img

    def getNearestFeature(self, x, y):
        #### TODO implement this
        return x, y


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

    if DEBUG_MODE:
        for prop, desc in vcaps.iteritems():
            print "  {0} ({1}): {2}".format(prop, desc, cap.get(prop))

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config['size'][0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config['size'][1])

    vidWidth = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vidHeight = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vidRate = cap.get(cv2.CAP_PROP_FPS)
    vidFormat = cap.get(cv2.CAP_PROP_FOURCC)

    ch = config['crosshair']
    if ch['enable']:
        xhair = Crosshair(vidWidth, vidHeight, ch, config['adjustments'])

    o = config['osd']
    if o['enable']:
        osd = OnScreenDisplay(o)
    else:
        osd = None

    if options.verbose:
        sys.stdout.write("    Video Device Index:  {0}\n".format(config['device']))
        sys.stdout.write("    Video Dimensions:    {0} x {1}\n".format(vidWidth,
                                                                       vidHeight))
        sys.stdout.write("    Video Frame Rate:    {0}\n".format(vidRate))
        sys.stdout.write("    Video Format:        {0}\n".format(vidFormat))
        sys.stdout.write("    On-Screen Display:   ")
        if o['enable']:
            sys.stdout.write("Enabled\n")
            sys.stdout.write("        Font Face:           {0}\n".format(o['face']))
            sys.stdout.write("        Font Scale:          {0}\n".format(o['scale']))
            sys.stdout.write("        Font Color:          {0}\n".format(o['color']))
            sys.stdout.write("        Font Thickness:      {0}\n".format(o['thickness']))
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("    Crosshair Display:   ")
        if ch['enable']:
            sys.stdout.write("Enabled\n")
            sys.stdout.write("        Thickness:           {0}\n".format(ch['thickness']))
            sys.stdout.write("        Color:               {0}\n".format(ch['color']))
            sys.stdout.write("        Alpha:               {0}\n".format(ch['alpha']))
            sys.stdout.write("        Highlight Color:     {0}\n".format(ch['highlightColor']))
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("    Realtime Controls ")
        if config['adjustments']:
            sys.stdout.write("Enabled\n")
        else:
            sys.stdout.write("Disabled\n")
        sys.stdout.write("\n")

    vidProc = VideoProcessing()
    kbd = KeyboardInput()

    #### TODO get calibration data
    cal = None
    measure = Measurement(vidWidth, vidHeight, cal)

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
            if dX is not None:
                img = osd.overlay(img, OnScreenDisplay.TOP_LEFT, 0,
                                  "X: {0}mm".format(round(dX, 2)))
            if dY is not None:
                img = osd.overlay(img, OnScreenDisplay.TOP_LEFT, 1,
                                  "Y: {0}mm".format(round(dY, 2)))
            if dist is not None:
                img = osd.overlay(img, OnScreenDisplay.TOP_LEFT, 2,
                                  "D: {0}mm".format(round(dist, 2)))
            if kbd.mode is not None:
                img = osd.overlay(img, OnScreenDisplay.TOP_RIGHT, 0,
                                  KeyboardInput.FEATURES[kbd.mode])

        # display the processed and overlayed video frame
        cv2.imshow('view', img)

        # process keyboard input
        run = kbd.input()

    # clean up everything and exit
    cap.release()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

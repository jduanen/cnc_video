"""X-Carve Microscope Tool Video Library"""

import argparse
import collections
import logging
import math
import os
import signal
import sys
import yaml

import numpy as np
import cv2


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
            logging.error("Invalid crosshair image width: %d", self.width)
            return False
        if self.height < 0 or self.height > MAX_VIDEO_HEIGHT:
            logging.error("Invalid crosshair image height: %d", self.height)
            return False
        if self.thick < 1 or self.thick > MAX_CROSSHAIR_THICKNESS:
            logging.error("Invalid crosshair thickness: %d", self.thick)
            return False
        if ((len(self.color) != 3) or (min(self.color) < 0) or
                (max(self.color) > 255)):
            logging.error("Invalid crosshair color: %s", self.color)
            return False
        if self.color == self.highlightColor:
            logging.warning("Crosshair and highlight colors are the same")
        if self.alpha < 0.0 or self.alpha > 1.0:
            logging.error("Invalid crosshair alpha: %f", self.alpha)
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
        """
        ovrly = self._render(img.copy(), self.hiH, self.hiV)
        if self.adjustments:
            self.alpha = (cv2.getTrackbarPos('alpha', 'view') / 100.0)
        cv2.addWeighted(ovrly, self.alpha, img, (1.0 - self.alpha), 0, img)


class OnScreenDisplay(object):
    """
    On-screen display ????
    <(optionally) put stuff in all four corners>
    """
    MAX_LINES = 3
    MAX_CHARS = 10
    TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT = range(4)

    def __init__(self, config):
        """
        Instantiate OSD object.

        @param confVals See 'osd' field in config struct dict
        """
        confVals = config['osd']
        self.fontFace = confVals['face']
        self.fontColor = confVals['color']
        self.fontScale = confVals['scale']
        self.fontThickness = confVals['thickness']

        txtSize, baseline = cv2.getTextSize("M" * OnScreenDisplay.MAX_CHARS,
                                            self.fontFace, self.fontScale,
                                            self.fontThickness)
        self.txtHeight = txtSize[1]
        self.maxStrWidth = txtSize[0]

        imgWidth = config['imgWidth']
        imgHeight = config['imgHeight']

        yOffset = 5
        xLeftOffset = 5
        xRightOffset = (imgWidth - (self.maxStrWidth + 1))
        lineSpacing = int(self.txtHeight / 3.0) + 3
        lineHeight = (self.txtHeight + lineSpacing)
        self.lineOrigins = [
            [   # TOP_LEFT
                (xLeftOffset, yOffset + self.txtHeight),
                (xLeftOffset, yOffset + (lineHeight * 2)),
                (xLeftOffset, yOffset + (lineHeight * 3))
            ],
            [   # TOP_RIGHT
                (xRightOffset, yOffset + self.txtHeight),
                (xRightOffset, yOffset + (lineHeight * 2)),
                (xRightOffset, yOffset + (lineHeight * 3))
            ],
            [   # BOTTOM_LEFT
                (xLeftOffset, imgHeight - yOffset),
                (xLeftOffset, imgHeight - (yOffset + lineHeight)),
                (xLeftOffset, imgHeight - (yOffset + (lineHeight * 2)))
            ],
            [   # BOTTOM_RIGHT
                (xRightOffset, imgHeight - yOffset),
                (xRightOffset, imgHeight - (yOffset + lineHeight)),
                (xRightOffset, imgHeight - (yOffset + (lineHeight * 2)))
            ]
        ]

    def overlay(self, img, corner, lineNum, text):
        """
        Overlay text on image at given location.
        """
        if corner < OnScreenDisplay.TOP_LEFT or \
           corner > OnScreenDisplay.BOTTOM_RIGHT:
            logging.error("Invalid OSD location value: %d", corner)
            raise ValueError

        origTextLen = len(text)
        (txtWidth, txtHeight), b = cv2.getTextSize(text, self.fontFace,
                                                   self.fontScale,
                                                   self.fontThickness)
        while (txtWidth > self.maxStrWidth):
            text = text[:-1]
            (txtWidth, txtHeight), b = cv2.getTextSize(text, self.fontFace,
                                                       self.fontScale,
                                                       self.fontThickness)
        if len(text) != origTextLen:
            logging.warning("Text too long; truncated")

        if lineNum < 0 or lineNum >= OnScreenDisplay.MAX_LINES:
            logging.error("Invalid OSD line number: %d", lineNum)
            raise ValueError

        bottomLeft = self.lineOrigins[corner][lineNum]
        cv2.putText(img, text, bottomLeft, self.fontFace, self.fontScale,
                    self.fontColor, self.fontThickness, cv2.LINE_AA, False)
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
        output = {}

        #### Detection Pipeline:
        ####  * cvt2gray
        ####  * cvSmooth
        ####  * cvThreshold
        ####  * cvCanny
        ####  * cvFindContours
        ####  * cvApproxPoly

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        output['variance'] = cv2.Laplacian(gray, cv2.CV_64F).var()

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
        return output

    def getNearestFeature(self, x, y):
        #### TODO implement this
        return x, y


#
# TEST
#
if __name__ == '__main__':
    print("TBD")

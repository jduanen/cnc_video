"""X-Carve Microscope Tool CNC Library"""

from xcarve import XCarve


class CNC(XCarve):
    """
    ????
    """
    def __init__(self, config):
        """
        Instantiate CNC object.

        ????
        """
        self.config = config
        super(CNC, self).__init__(config)
        self.maxFocus = (None, None)  # (focusVal, zPos)
        self.focus = (None, None)     # (focusVal, zPos)

    def focus(self, focusVal):
        x, y, z = self.getPosition()
        return None


#
# TEST
#
if __name__ == '__main__':
    print("TBD")

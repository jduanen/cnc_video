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

    def focus(self, variance):
        #### FIXME
        return variance


#
# TEST
#
if __name__ == '__main__':
    print("TBD")

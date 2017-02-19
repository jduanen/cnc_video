"""X-Carve GRBL Device Interface -- Library"""

import logging

from grbl import GrblDevice

# X-Carve travel limits (in mm)
MAX_X = 260.00
MAX_Y = 260.00
MAX_Z = 100.00


class XCarve(GrblDevice):
    def __init__(self, config):
        """
        ????

        @param serialDev ?
        """
        cnc = config['cnc']
        if 'device' not in cnc:
            logging.error("Must provide serial device name")
            raise RuntimeError
        serialDevice = cnc['device']
        super(XCarve, self).__init__(serialDevice)

    def home(self):
        #### FIXME
        return

    def probe(self):
        #### FIXME
        return

    def gotoMaxZ(self):
        #### FIXME
        return


#
# TEST
#
if __name__ == '__main__':
    #### FIXME
    print("TBD")

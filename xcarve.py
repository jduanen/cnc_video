"""X-Carve GRBL Device Interface -- Library"""

from grbl import GrblDevice


class XCarve(GrblDevice):
    def __init__(self, serialDev):
        """
        ????

        @param serialDev ?
        """
        super(XCarve, self).__init__(serialDev)


#
# TEST
#
if __name__ == '__main__':
	#### FIXME
    print("TBD")
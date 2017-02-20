"""Utility Functions for the CNC_VIDEO app -- Library"""

import collections
import logging
import threading
import time


# Map of type names into types
TYPES = {
    'int': int,
    'float': float,
    'string': str,
    'boolean': bool
}


# Take a type name and a string and return the value cast to the given type.
def typeCast(typ, str):
    if typ not in TYPES.keys():
        logging.error("Invalid type: %s", typ)
        raise ValueError
    return TYPES[typ](str)


# Merge a new dict into an old one, updating the old one (recursively).
def dictMerge(old, new):
    for k, v in new.iteritems():
        if (k in old and isinstance(old[k], dict) and
            isinstance(new[k], collections.Mapping)):
            dictMerge(old[k], new[k])
        else:
            old[k] = new[k]


class Alarm(threading.Thread):
    def __init__(self, queue, timeout):
        self.q = queue
        self.timeout = timeout
        threading.Thread.__init__(self)
        self.setDaemon(True)

    def run(self):
        time.sleep(self.timeout)
        self.q.put(None)


#
# TEST
#
if __name__ == '__main__':
    r = typeCast('int', "1")
    print type(r), r
    r = typeCast('float', "1")
    print type(r), r
    r = typeCast('string', "1")
    print type(r), r
    r = typeCast('boolean', "1")
    print type(r), r
    r = typeCast("foo", "1")
    print type(r), r

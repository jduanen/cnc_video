"""Utility Functions for the CNC_VIDEO app -- Library"""


# Merge a new dict into an old one, updating the old one (recursively).
def dictMerge(old, new):
    for k, v in new.iteritems():
        if (k in old and isinstance(old[k], dict) and
            isinstance(new[k], collections.Mapping)):
            dictMerge(old[k], new[k])
        else:
            old[k] = new[k]


#
# TEST
#
if __name__ == '__main__':
    print("TBD")

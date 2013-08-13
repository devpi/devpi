import sys
import py
import logging

__version__ = '1.0rc1'

log = logging.getLogger(__name__)

def cached_property(f):
    """returns a cached property that is calculated by function f"""
    # taken from
    # http://code.activestate.com/recipes/576563-cached-property/
    def get(self):
        try:
            return self._property_cache[f]
        except AttributeError:
            self._property_cache = {}
            x = self._property_cache[f] = f(self)
            return x
        except KeyError:
            x = self._property_cache[f] = f(self)
            return x

    return property(get)

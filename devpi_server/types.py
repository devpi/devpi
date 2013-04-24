
def propmapping(name, type=None):
    if type is None:
        def fget(self):
            return self._mapping.get(name)
    else:
        def fget(self):
            x = self._mapping.get(name)
            if x is not None:
                x = type(x)
            return x
    fget.__name__ = name
    return property(fget)

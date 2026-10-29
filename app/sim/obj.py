"""A dict with attribute access and identity equality.

Orders, items, SKUs and trips are shared by reference between the simulator, the agents and the
event bus (an event carries the very item a picker failed to find). Identity equality keeps
`x in list` and `list.remove(x)` exact and fast, and the dict base keeps snapshots JSON-ready."""


class Obj(dict):
    __slots__ = ()

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        self[k] = v

    def __delattr__(self, k):
        del self[k]

    __eq__ = object.__eq__
    __ne__ = object.__ne__
    __hash__ = object.__hash__

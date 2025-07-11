import sqlite3
from collections import OrderedDict
from collections.abc import MutableMapping
from pathlib import Path

from .setup import P, path_data

class MemCache(MutableMapping):
    def __init__(self, *args, **kwargs):
        self.__maxsize = kwargs.pop("maxsize", None)
        self.__d = OrderedDict(*args, **kwargs)

    @property
    def maxsize(self):
        return self.__maxsize

    def __getitem__(self, key):
        if key in self.__d:
            self.__d.move_to_end(key)
        return self.__d[key]

    def __setitem__(self, key, value):
        if key in self.__d:
            self.__d.move_to_end(key)
        elif len(self.__d) == self.maxsize:
            self.__d.popitem(last=False)
        self.__d[key] = value

    def __delitem__(self, key):
        del self.__d[key]

    def __iter__(self):
        return iter(self.__d)

    def __len__(self):
        return len(self.__d)

    def __repr__(self):
        return repr(self.__d)

    # 여기까지 필수

    def clear(self):
        return self.__d.clear()

    def keys(self):
        return self.__d.keys()

    def values(self):
        return self.__d.values()

    def items(self):
        return self.__d.items()

    def pop(self, *args):
        return self.__d.pop(*args)

    def __contains__(self, item):
        return item in self.__d


class CacheUtil:
    cache_dict = None
    cache_file = Path(path_data).joinpath(f"db/{P.package_name}.db")

    @classmethod
    def get_cache(cls, maxsize=100) -> dict:
        if cls.cache_dict is not None:
            return cls.cache_dict
        try:
            con = sqlite3.connect(cls.cache_file)
            try:
                with con:
                    con.executescript(f"DROP TABLE {P.package_name}_cache; VACUUM;")
            except Exception:
                pass
            con.close()
        except Exception:
            pass
        cls.cache_dict = MemCache(maxsize=maxsize)
        return cls.cache_dict

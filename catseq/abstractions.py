from functools import wraps
from abc import ABCMeta, abstractmethod, ABC
from dataclasses import dataclass
from dataclasses_json import dataclass_json

## ABDC: ABstract Data Class
class ABDCMeta(ABCMeta):
    """
    A metaclass that combines ABCMeta functionality with the automatic application
    of @dataclass and @dataclass_json decorators.
    """
    def __new__(mcs, name, bases, dct):
        # First, create the class using the parent metaclass's __new__.
        # This correctly handles the @abstractmethod functionality from ABCMeta.
        cls = super().__new__(mcs, name, bases, dct)

        # apply the decorators to all classes,
        # including abstract bases
        decorated_cls = dataclass_json(dataclass(cls))
        return decorated_cls


class ABDC(metaclass=ABDCMeta):
    """Helper class that provides a standard way to create an ABDC using
    inheritance.
    """
    __slots__ = ()

## single instance
def singleton(cls):
    """
        wrap __init__ & __new__ to make sure single instance
        __post_init__ is not wrapped hence __post_init__ can be saperately call again to init dynamical para
    """
    cls._instance = None
    cls._initialized = False
    cls._origin__new__ = cls.__new__
    cls._origin__init__ = cls.__init__
    wraps(cls._origin__new__)
    def single_new(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = cls._origin__new__(cls)
        else:
            raise ValueError(f"Instance of {cls.__name__} already exists.")
        return cls._instance
    wraps(cls._origin__init__)
    def single_init(self, *args, **kwargs):
        if not self.__class__._initialized:
            self.__class__._initialized = True
            self.__class__._origin__init__(self,*args, **kwargs)
        else:
            raise ValueError(f"Instance of {self.__class__.__name__} already initialized.")
    cls.__new__ = single_new
    cls.__init__ = single_init
    return cls

## h5py
import h5py
import warnings
from dataclasses import fields
import numpy as np
from typing import cast
class Savable(ABC):
    """Savable is compatible with ABDC during multi-inherit, according to The "Most Derived" Metaclass Rule"""
    @abstractmethod
    def save_to_h5(self, group:h5py.Group, overwrite: bool = False):
        """Saves the object to an HDF5 group."""
        pass

from dataclasses import Field
from typing import Any

def defaut_save_field(group: h5py.Group, key:str, value: Any, overwrite:bool=False):
            if isinstance(value, (int, float, str, tuple)):
                group[key] = value
            elif isinstance(value, (list, np.ndarray)):
                safe_create_dataset(
                    group, key,
                    value,
                    overwrite
                )
            elif isinstance(value, Savable):
                savable_child = cast(Savable, value)
                savable_child.save_to_h5(
                    group.create_group(key),
                    overwrite
                )
            # TODO: Leave the storage of Morphism to later update
            # elif isinstance(value, Expr):
            #     group[key] = value.__repr__()
            else:
                raise TypeError(f"Unknown type for default save_to_h5{value.__class__}")



class SavableABDC(ABDC, Savable):
    """default save method for ABDC"""
    def save_to_h5(self, group, overwrite = False):
        for f in fields(self):
            key = f.name
            value = getattr(self, f.name)
            defaut_save_field(group, key, value, overwrite)

def safe_create_dataset(group: h5py.Group, name: str, data, overwrite: bool = False):
    """
    Safely creates a dataset in an HDF5 group, with an option to overwrite.
    """
    if name in group:
        if overwrite:
            warnings.warn(f"Overwriting existing dataset '{name}' in group '{group.name}'.")
            del group[name]
        else:
            raise FileExistsError(
                f"Dataset '{name}' already exists in group '{group.name}'. "
                "Set overwrite=True to allow replacement."
            )
    return group.create_dataset(name, data=data)

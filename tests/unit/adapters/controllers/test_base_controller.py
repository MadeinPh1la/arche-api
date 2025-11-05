from __future__ import annotations

import pytest

from stacklion_api.adapters.controllers.base import BaseController


def test_basecontroller_is_instantiable() -> None:
    c = BaseController()
    assert isinstance(c, BaseController)


def test_basecontroller_has_no_instance_dict_and_rejects_new_attrs() -> None:
    c = BaseController()
    # __slots__ = () implies no __dict__
    assert not hasattr(c, "__dict__")
    # arbitrary attributes should be rejected
    with pytest.raises(AttributeError):
        c.anything = 123  # type: ignore[attr-defined]


def test_subclass_can_define_explicit_slots() -> None:
    class NamedController(BaseController):
        __slots__ = ("name",)

        def __init__(self, name: str) -> None:
            self.name = name

    nc = NamedController("quotes")
    assert isinstance(nc, BaseController)
    assert nc.name == "quotes"
    # still no dynamic __dict__ unless subclass defines one
    assert not hasattr(nc, "__dict__")


def test_subclass_without_slots_inherits_dynamic_attrs() -> None:
    class PlainController(BaseController):
        # no __slots__ declared; inherits normal Python behavior with __dict__
        pass

    pc = PlainController()
    assert isinstance(pc, BaseController)
    # Because PlainController doesn't declare __slots__, it has a __dict__:
    assert hasattr(pc, "__dict__")
    # and arbitrary attributes can be added
    pc.x = 1  # should NOT raise
    assert pc.x == 1

from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class GNUAttributes:
    attributes: List["Attribute"] = field(default_factory=list)
    packed: bool = False
    align_override: Optional[int] = None
    section_name: Optional[str] = None
    weak: bool = False
    noreturn: bool = False
    always_inline: bool = False
    noinline: bool = False
    unused: bool = False
    deprecated: bool = False
    format_attr: Optional["Attribute"] = None
    constructor_attr: Optional["Attribute"] = None
    destructor_attr: Optional["Attribute"] = None

    def merge(self, other: "GNUAttributes") -> "GNUAttributes":
        self.attributes.extend(other.attributes)
        self.packed = self.packed or other.packed
        if other.align_override is not None:
            cur = 0 if self.align_override is None else self.align_override
            self.align_override = max(cur, other.align_override)
        if other.section_name is not None:
            if (
                self.section_name is not None
                and self.section_name != other.section_name
            ):
                raise TypeError("conflicting section attributes")
            self.section_name = other.section_name
        self.weak = self.weak or other.weak
        self.noreturn = self.noreturn or other.noreturn
        self.always_inline = self.always_inline or other.always_inline
        self.noinline = self.noinline or other.noinline
        self.unused = self.unused or other.unused
        self.deprecated = self.deprecated or other.deprecated
        if other.format_attr is not None:
            self.format_attr = other.format_attr
        if other.constructor_attr is not None:
            self.constructor_attr = other.constructor_attr
        if other.destructor_attr is not None:
            self.destructor_attr = other.destructor_attr
        return self


from .Attribute import Attribute

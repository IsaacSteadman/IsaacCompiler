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
    used: bool = False
    always_inline: bool = False
    noinline: bool = False
    unused: bool = False
    deprecated: bool = False
    fallthrough: bool = False
    alias_name: Optional[str] = None
    cleanup_name: Optional[str] = None
    error_message: Optional[str] = None
    warning_message: Optional[str] = None
    mode_name: Optional[str] = None
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
        self.used = self.used or other.used
        self.always_inline = self.always_inline or other.always_inline
        self.noinline = self.noinline or other.noinline
        if self.always_inline and self.noinline:
            raise TypeError("always_inline and noinline attributes conflict")
        self.unused = self.unused or other.unused
        self.deprecated = self.deprecated or other.deprecated
        self.fallthrough = self.fallthrough or other.fallthrough
        if other.alias_name is not None:
            if self.alias_name is not None and self.alias_name != other.alias_name:
                raise TypeError("conflicting alias attributes")
            self.alias_name = other.alias_name
        if other.cleanup_name is not None:
            if self.cleanup_name is not None and self.cleanup_name != other.cleanup_name:
                raise TypeError("conflicting cleanup attributes")
            self.cleanup_name = other.cleanup_name
        if other.error_message is not None:
            self.error_message = other.error_message
        if other.warning_message is not None:
            self.warning_message = other.warning_message
        if other.mode_name is not None:
            if self.mode_name is not None and self.mode_name != other.mode_name:
                raise TypeError("conflicting mode attributes")
            self.mode_name = other.mode_name
        if other.format_attr is not None:
            self.format_attr = other.format_attr
        if other.constructor_attr is not None:
            self.constructor_attr = other.constructor_attr
        if other.destructor_attr is not None:
            self.destructor_attr = other.destructor_attr
        return self


from .Attribute import Attribute

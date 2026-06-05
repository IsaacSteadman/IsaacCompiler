from typing import Optional, Union


def get_context_default_alignment(
    owner: Optional[Union["ContextMember", "CompileContext"]],
) -> Optional[int]:
    cur = owner
    while cur is not None:
        if isinstance(cur, CompileContext):
            return normalize_default_alignment(cur.default_alignment)
        if isinstance(cur, ContextMember):
            cur = cur.parent
        else:
            break
    return None


def get_flexible_array_elem_type(typ: "BaseType") -> "BaseType":
    typ = strip_cv_qualifiers(typ)
    assert isinstance(typ, QualType)
    assert typ.qual_id == QualType.QUAL_ARR
    return typ.tgt_type


def align_of(
    typ: "BaseType",
    is_arg: bool = False,
    default_alignment: Optional[int] = None,
    owner: Optional[Union["ContextMember", "CompileContext"]] = None,
) -> int:
    if owner is None and isinstance(typ, ContextMember):
        owner = typ
    resolved_default_alignment = normalize_default_alignment(
        default_alignment
        if default_alignment is not None
        else get_context_default_alignment(owner)
    )
    if isinstance(typ, QualType):
        if typ.qual_id == QualType.QUAL_ARR:
            if typ.ext_inf is None and isinstance(owner, StructType):
                return align_of(
                    get_flexible_array_elem_type(typ),
                    default_alignment=resolved_default_alignment,
                    owner=owner,
                )
            if is_arg or typ.ext_inf is None:
                return default_align_for_size(8, resolved_default_alignment)
            return align_of(
                typ.tgt_type,
                default_alignment=resolved_default_alignment,
                owner=owner,
            )
        elif typ.qual_id in {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_REF}:
            return default_align_for_size(8, resolved_default_alignment)
        elif typ.qual_id == QualType.QUAL_ATOMIC:
            return max(
                align_of(
                    typ.tgt_type,
                    default_alignment=resolved_default_alignment,
                    owner=owner,
                ),
                host_atomic_align_for_size(
                    size_of(
                        typ.tgt_type,
                        default_alignment=resolved_default_alignment,
                        owner=owner,
                    )
                ),
            )
        elif typ.qual_id in {
            QualType.QUAL_CONST,
            QualType.QUAL_DEF,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
        }:
            return align_of(
                typ.tgt_type,
                default_alignment=resolved_default_alignment,
                owner=owner,
            )
        else:
            raise ValueError("Unrecognized QualType.qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return align_of(
            typ.typ, default_alignment=resolved_default_alignment, owner=owner
        )
    elif isinstance(typ, PrimitiveType):
        return default_align_for_size(typ.size, resolved_default_alignment)
    elif isinstance(typ, EnumType):
        return align_of(
            typ.the_base_type,
            default_alignment=resolved_default_alignment,
            owner=typ,
        )
    elif isinstance(typ, StructType):
        return typ._ensure_layout().alignment
    elif isinstance(typ, ClassType):
        align = 1
        if typ.the_base_type is not None:
            align = max(
                align,
                align_of(
                    typ.the_base_type,
                    default_alignment=resolved_default_alignment,
                    owner=typ,
                ),
            )
        for ctx_var in typ.var_order:
            align = max(
                align,
                align_of(
                    ctx_var.typ,
                    default_alignment=resolved_default_alignment,
                    owner=typ,
                ),
            )
        if typ.align_override is not None:
            align = max(align, typ.align_override)
        return align
    elif isinstance(typ, UnionType):
        align = 1 if typ.is_packed else 1
        if typ.the_base_type is not None:
            base_align = (
                1
                if typ.is_packed
                else align_of(
                    typ.the_base_type,
                    default_alignment=resolved_default_alignment,
                    owner=typ,
                )
            )
            align = max(align, base_align)
        for ctx_var in typ.member_order:
            align = max(
                align,
                (
                    1
                    if typ.is_packed
                    else align_of(
                        ctx_var.typ,
                        default_alignment=resolved_default_alignment,
                        owner=typ,
                    )
                ),
            )
        if typ.align_override is not None:
            align = max(align, typ.align_override)
        return align
    else:
        raise TypeError("Unrecognized type: %s" % typ.__class__.__name__)


def size_of(
    typ: "BaseType",
    is_arg: bool = False,
    default_alignment: Optional[int] = None,
    owner: Optional[Union["ContextMember", "CompileContext"]] = None,
):
    if owner is None and isinstance(typ, ContextMember):
        owner = typ
    resolved_default_alignment = normalize_default_alignment(
        default_alignment
        if default_alignment is not None
        else get_context_default_alignment(owner)
    )
    if isinstance(typ, QualType):
        if typ.qual_id == QualType.QUAL_ARR:
            if typ.ext_inf is None and isinstance(owner, StructType):
                return 0
            if is_arg or typ.ext_inf is None:
                return 8
            return (
                size_of(
                    typ.tgt_type,
                    default_alignment=resolved_default_alignment,
                    owner=owner,
                )
                * typ.ext_inf
            )
        elif typ.qual_id in {QualType.QUAL_FN, QualType.QUAL_PTR, QualType.QUAL_REF}:
            return 8
        elif typ.qual_id in {
            QualType.QUAL_CONST,
            QualType.QUAL_DEF,
            QualType.QUAL_REG,
            QualType.QUAL_VOLATILE,
            QualType.QUAL_ATOMIC,
        }:
            return size_of(
                typ.tgt_type,
                default_alignment=resolved_default_alignment,
                owner=owner,
            )
        else:
            raise ValueError("Unrecognized QualType.qual_id = %u" % typ.qual_id)
    elif isinstance(typ, IdentifiedQualType):
        return size_of(
            typ.typ, default_alignment=resolved_default_alignment, owner=owner
        )
    elif isinstance(typ, PrimitiveType):
        return typ.size
    elif isinstance(typ, EnumType):
        return size_of(
            typ.the_base_type,
            default_alignment=resolved_default_alignment,
            owner=typ,
        )
    elif isinstance(typ, StructType):
        return typ._ensure_layout().size
    elif isinstance(typ, ClassType):
        sz = (
            0
            if typ.the_base_type is None
            else size_of(
                typ.the_base_type,
                default_alignment=resolved_default_alignment,
                owner=typ,
            )
        )
        for ctx_var in typ.var_order:
            sz = align_up(
                sz,
                align_of(
                    ctx_var.typ,
                    default_alignment=resolved_default_alignment,
                    owner=typ,
                ),
            )
            sz += size_of(
                ctx_var.typ,
                default_alignment=resolved_default_alignment,
                owner=typ,
            )
        return align_up(
            sz, align_of(typ, default_alignment=resolved_default_alignment, owner=typ)
        )
    elif isinstance(typ, UnionType):
        # TODO: remove BaseType from UnionType
        sz = (
            0
            if typ.the_base_type is None
            else size_of(
                typ.the_base_type,
                default_alignment=resolved_default_alignment,
                owner=typ,
            )
        )
        for v in typ.member_order:
            assert isinstance(v, ContextVariable)
            sz = max(
                sz,
                size_of(v.typ, default_alignment=resolved_default_alignment, owner=typ),
            )
        align = align_of(typ, default_alignment=resolved_default_alignment, owner=typ)
        if typ.is_packed and typ.align_override is None:
            return sz
        return align_up(sz, align)
    else:
        raise TypeError("Unrecognized type: %s" % typ.__class__.__name__)
    # TODO: add Typedef support


from .align_util import (
    align_up,
    default_align_for_size,
    host_atomic_align_for_size,
    normalize_default_alignment,
)
from .BaseType import BaseType
from .ContextMember import ContextMember
from .CompileContext import CompileContext
from .EnumType import EnumType
from .IdentifiedQualType import IdentifiedQualType
from .PrimitiveType import PrimitiveType
from .QualType import QualType
from .StructType import StructType
from .UnionType import UnionType
from .ClassType import ClassType
from .ContextVariable import ContextVariable
from .qual_atomic_type_util import strip_cv_qualifiers

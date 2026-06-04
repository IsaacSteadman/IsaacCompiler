from dataclasses import dataclass, field
import struct
from typing import BinaryIO, List, Union

from .object_file import StackVMObject, dumps_sbo, loads_sbo


SBA_MAGIC = b"\xf7SVA\0\0\0\0"
SBA_VERSION = 1
SBA_HEADER_SIZE = 24
SBA_MEMBER_HEADER_SIZE = 16

_HEADER = struct.Struct("<8sQQ")
_MEMBER_HEADER = struct.Struct("<QQ")

assert _HEADER.size == SBA_HEADER_SIZE
assert _MEMBER_HEADER.size == SBA_MEMBER_HEADER_SIZE


@dataclass
class ArchiveMember:
    name: str
    obj: StackVMObject


@dataclass
class StackVMArchive:
    members: List[ArchiveMember] = field(default_factory=list)


def _encode_member_name(name: str) -> bytes:
    if not name:
        raise ValueError("archive member names cannot be empty")
    if "\0" in name:
        raise ValueError("archive member names cannot contain null bytes")
    return name.encode("utf-8")


def dumps_sba(archive: StackVMArchive) -> bytes:
    members = []
    for member in archive.members:
        if not isinstance(member, ArchiveMember):
            raise ValueError("archive members must be ArchiveMember instances")
        members.append((_encode_member_name(member.name), dumps_sbo(member.obj)))

    out = bytearray(_HEADER.pack(SBA_MAGIC, SBA_VERSION, len(members)))
    for name, obj_data in members:
        out.extend(_MEMBER_HEADER.pack(len(name), len(obj_data)))
        out.extend(name)
        out.extend(obj_data)
    return bytes(out)


def write_sba(archive: StackVMArchive, target: Union[str, BinaryIO]) -> None:
    data = dumps_sba(archive)
    if hasattr(target, "write"):
        target.write(data)
        return
    with open(target, "wb") as fl:
        fl.write(data)


def loads_sba(data: bytes) -> StackVMArchive:
    if len(data) < SBA_HEADER_SIZE:
        raise ValueError("archive file is too short to contain a header")
    magic, version, member_count = _HEADER.unpack_from(data)
    if magic != SBA_MAGIC:
        raise ValueError("invalid .sba magic")
    if version != SBA_VERSION:
        raise ValueError("unsupported .sba version: %u" % version)

    offset = SBA_HEADER_SIZE
    members = []
    for _index in range(member_count):
        if offset + SBA_MEMBER_HEADER_SIZE > len(data):
            raise ValueError("archive member header extends past the end of the file")
        name_size, obj_size = _MEMBER_HEADER.unpack_from(data, offset)
        offset += SBA_MEMBER_HEADER_SIZE
        member_end = offset + name_size + obj_size
        if member_end > len(data):
            raise ValueError("archive member extends past the end of the file")
        name_data = data[offset : offset + name_size]
        offset += name_size
        try:
            name = name_data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("archive member name is not valid UTF-8") from exc
        _encode_member_name(name)
        members.append(ArchiveMember(name, loads_sbo(data[offset:member_end])))
        offset = member_end
    if offset != len(data):
        raise ValueError("archive file has trailing data")
    return StackVMArchive(members)


def load_sba(source: Union[str, BinaryIO]) -> StackVMArchive:
    if hasattr(source, "read"):
        return loads_sba(source.read())
    with open(source, "rb") as fl:
        return loads_sba(fl.read())

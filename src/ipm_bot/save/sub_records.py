"""Sub-record parser for BinaryFormatter streams.

Extends the top-level parser to chase MemberReference objects into their
concrete sub-records: ArraySinglePrimitive, BinaryArray, ClassWithMembersAndTypes,
ClassWithId, and BinaryObjectString.

Produces a mapping of object_id -> SubRecord with file offsets and decoded values.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import Any

from .parser import (
    _BinaryReader,
    _FieldDescriptor,
    _MemberReference,
    _NullRun,
    _read_additional_info,
    _read_top_level_value,
    BinaryType,
    PrimitiveType,
    RecordType,
    RAW_PLAYER_DATA_HEADER,
)
from .exceptions import UnsupportedSaveFormatError


DOTNET_TICKS_MASK = 0x3FFFFFFFFFFFFFFF
DOTNET_BASE_DATETIME = datetime(1, 1, 1)

# Element sizes for primitive types
PRIMITIVE_SIZES: dict[PrimitiveType, int] = {
    PrimitiveType.BOOLEAN: 1,
    PrimitiveType.BYTE: 1,
    PrimitiveType.CHAR: 2,
    PrimitiveType.INT16: 2,
    PrimitiveType.INT32: 4,
    PrimitiveType.INT64: 8,
    PrimitiveType.DOUBLE: 8,
    PrimitiveType.SINGLE: 4,
    PrimitiveType.DATETIME: 8,
    PrimitiveType.TIMESPAN: 8,
    PrimitiveType.UINT16: 2,
    PrimitiveType.UINT32: 4,
    PrimitiveType.UINT64: 8,
    PrimitiveType.SBYTE: 1,
    PrimitiveType.DECIMAL: 16,
}


class BinaryArrayType(IntEnum):
    SINGLE = 0
    JAGGED = 1
    RECTANGULAR = 2
    SINGLE_OFFSET = 3
    JAGGED_OFFSET = 4
    RECTANGULAR_OFFSET = 5


@dataclass(frozen=True, slots=True)
class ArraySubRecord:
    """A parsed primitive array sub-record."""
    object_id: int
    primitive_type: PrimitiveType
    length: int
    payload_file_offset: int
    payload_byte_length: int
    values: tuple[Any, ...]
    field_name: str | None = None


@dataclass(frozen=True, slots=True)
class RectangularArraySubRecord:
    """A parsed rectangular (multi-dimensional) primitive array sub-record."""
    object_id: int
    primitive_type: PrimitiveType
    rank: int
    dimensions: tuple[int, ...]
    payload_file_offset: int
    payload_byte_length: int
    values: tuple[Any, ...]
    field_name: str | None = None


@dataclass(frozen=True, slots=True)
class StringSubRecord:
    """A parsed BinaryObjectString sub-record."""
    object_id: int
    value: str
    file_offset: int
    field_name: str | None = None


@dataclass(frozen=True, slots=True)
class ClassSubRecord:
    """A parsed class instance sub-record (ClassWithMembersAndTypes or ClassWithId)."""
    object_id: int
    class_name: str
    member_names: tuple[str, ...]
    member_values: dict[str, Any]
    file_offset: int
    field_name: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectArraySubRecord:
    """A parsed ArraySingleObject sub-record (array of objects/references)."""
    object_id: int
    length: int
    file_offset: int
    element_refs: tuple[int | None, ...]
    field_name: str | None = None


SubRecord = ArraySubRecord | RectangularArraySubRecord | StringSubRecord | ClassSubRecord | ObjectArraySubRecord


@dataclass(frozen=True, slots=True)
class _ClassMetadata:
    """Retained class shape for ClassWithId back-references."""
    class_name: str
    descriptors: tuple[_FieldDescriptor, ...]
    library_id: int


@dataclass(slots=True)
class SubRecordParseResult:
    """Full parse result with all sub-records indexed by object ID."""
    top_level_field_names: dict[int, str]  # object_id -> field name from top-level
    sub_records: dict[int, SubRecord]
    parse_end_offset: int
    total_file_size: int
    warnings: list[str] = field(default_factory=list)


def parse_sub_records(source: str | Path | bytes) -> SubRecordParseResult:
    """Parse the full BinaryFormatter stream including all sub-records."""
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        data = source

    if not data.startswith(RAW_PLAYER_DATA_HEADER):
        raise UnsupportedSaveFormatError("Data does not start with BinaryFormatter header.")

    reader = _BinaryReader(data)

    # ── Header ──
    _rt = RecordType(reader.read_byte())  # SerializedStreamHeader
    _root_id = reader.read_int32()
    _header_id = reader.read_int32()
    _major = reader.read_int32()
    _minor = reader.read_int32()

    # ── BinaryLibrary ──
    _lib_rt = RecordType(reader.read_byte())
    _lib_id = reader.read_int32()
    _assembly = reader.read_length_prefixed_string()

    # ── Root ClassWithMembersAndTypes ──
    _root_rt = RecordType(reader.read_byte())
    _obj_id = reader.read_int32()
    _class_name = reader.read_length_prefixed_string()
    member_count = reader.read_int32()

    member_names = [reader.read_length_prefixed_string() for _ in range(member_count)]
    binary_types = [BinaryType(reader.read_byte()) for _ in range(member_count)]
    descriptors = [
        _FieldDescriptor(
            name=name,
            binary_type=bt,
            additional_info=_read_additional_info(reader, bt),
        )
        for name, bt in zip(member_names, binary_types, strict=True)
    ]
    _class_lib_id = reader.read_int32()

    # ── Read top-level member values, tracking MemberReferences ──
    top_level_refs: dict[int, str] = {}  # object_id -> field_name
    for desc in descriptors:
        value = _read_top_level_value(reader, desc)
        if isinstance(value, _MemberReference):
            top_level_refs[value.object_id] = desc.name

    # ── Parse sub-records ──
    sub_records: dict[int, SubRecord] = {}
    class_metadata: dict[int, _ClassMetadata] = {}  # object_id -> class shape
    warnings: list[str] = []

    while reader._offset < len(data):
        record_offset = reader._offset
        try:
            rt = RecordType(reader.read_byte())
        except (ValueError, IndexError):
            warnings.append(f"Unknown byte 0x{data[record_offset]:02X} at 0x{record_offset:04X}")
            break

        if rt == RecordType.MESSAGE_END:
            break

        elif rt == RecordType.ARRAY_SINGLE_PRIMITIVE:
            obj_id = reader.read_int32()
            array_length = reader.read_int32()
            prim_type = PrimitiveType(reader.read_byte())
            payload_offset = reader._offset
            elem_size = PRIMITIVE_SIZES.get(prim_type, 0)
            payload_bytes = array_length * elem_size

            values = _read_primitive_array(reader, prim_type, array_length)
            field_name = top_level_refs.get(obj_id)

            sub_records[obj_id] = ArraySubRecord(
                object_id=obj_id,
                primitive_type=prim_type,
                length=array_length,
                payload_file_offset=payload_offset,
                payload_byte_length=payload_bytes,
                values=tuple(values),
                field_name=field_name,
            )

        elif rt == RecordType.BINARY_ARRAY:
            obj_id = reader.read_int32()
            array_type_byte = reader.read_byte()
            rank = reader.read_int32()
            dimensions = tuple(reader.read_int32() for _ in range(rank))

            # Read BinaryTypeEnum for element type
            elem_binary_type = BinaryType(reader.read_byte())
            elem_additional_info = _read_additional_info(reader, elem_binary_type)

            total_elements = 1
            for d in dimensions:
                total_elements *= d

            if elem_binary_type == BinaryType.PRIMITIVE and isinstance(elem_additional_info, PrimitiveType):
                prim_type = elem_additional_info
                payload_offset = reader._offset
                elem_size = PRIMITIVE_SIZES.get(prim_type, 0)
                payload_bytes = total_elements * elem_size
                values = _read_primitive_array(reader, prim_type, total_elements)
                field_name = top_level_refs.get(obj_id)

                sub_records[obj_id] = RectangularArraySubRecord(
                    object_id=obj_id,
                    primitive_type=prim_type,
                    rank=rank,
                    dimensions=dimensions,
                    payload_file_offset=payload_offset,
                    payload_byte_length=payload_bytes,
                    values=tuple(values),
                    field_name=field_name,
                )
            else:
                # Non-primitive array elements (objects, strings, etc.)
                # These are followed by individual record entries
                field_name = top_level_refs.get(obj_id)
                # Read element records
                element_refs: list[int | None] = []
                for _ in range(total_elements):
                    elem_rt = RecordType(reader.read_byte())
                    if elem_rt == RecordType.MEMBER_REFERENCE:
                        element_refs.append(reader.read_int32())
                    elif elem_rt == RecordType.OBJECT_NULL:
                        element_refs.append(None)
                    elif elem_rt == RecordType.BINARY_OBJECT_STRING:
                        s_obj_id = reader.read_int32()
                        s_val = reader.read_length_prefixed_string()
                        sub_records[s_obj_id] = StringSubRecord(
                            object_id=s_obj_id, value=s_val,
                            file_offset=reader._offset, field_name=None,
                        )
                        element_refs.append(s_obj_id)
                    elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE_256:
                        null_count = reader.read_byte()
                        element_refs.extend([None] * null_count)
                    elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE:
                        null_count = reader.read_int32()
                        element_refs.extend([None] * null_count)
                    else:
                        warnings.append(
                            f"Unhandled element record type {rt.name} in BinaryArray obj_id={obj_id} at 0x{reader._offset:04X}"
                        )
                        # put byte back and break
                        reader._offset -= 1
                        break

                sub_records[obj_id] = ObjectArraySubRecord(
                    object_id=obj_id,
                    length=total_elements,
                    file_offset=record_offset,
                    element_refs=tuple(element_refs),
                    field_name=field_name,
                )

        elif rt == RecordType.ARRAY_SINGLE_OBJECT:
            obj_id = reader.read_int32()
            array_length = reader.read_int32()
            field_name = top_level_refs.get(obj_id)
            element_refs = []
            for _ in range(array_length):
                if reader._offset >= len(data):
                    break
                elem_rt = RecordType(reader.read_byte())
                if elem_rt == RecordType.MEMBER_REFERENCE:
                    element_refs.append(reader.read_int32())
                elif elem_rt == RecordType.OBJECT_NULL:
                    element_refs.append(None)
                elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE_256:
                    null_count = reader.read_byte()
                    element_refs.extend([None] * null_count)
                elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE:
                    null_count = reader.read_int32()
                    element_refs.extend([None] * null_count)
                elif elem_rt == RecordType.BINARY_OBJECT_STRING:
                    s_obj_id = reader.read_int32()
                    s_val = reader.read_length_prefixed_string()
                    sub_records[s_obj_id] = StringSubRecord(
                        object_id=s_obj_id, value=s_val,
                        file_offset=reader._offset, field_name=None,
                    )
                    element_refs.append(s_obj_id)
                elif elem_rt in (
                    RecordType.CLASS_WITH_MEMBERS_AND_TYPES,
                    RecordType.CLASS_WITH_ID,
                ):
                    # Inline class record as array element — parse it
                    reader._offset -= 1  # put back the record type byte
                    _parse_class_record(
                        reader, rt=elem_rt, data=data, sub_records=sub_records,
                        class_metadata=class_metadata, top_level_refs=top_level_refs,
                        warnings=warnings,
                    )
                    # The last parsed record's object_id is the element ref
                    # This is tricky — for now, just note it was inline
                    element_refs.append(None)
                else:
                    warnings.append(
                        f"Unhandled element record {elem_rt.name} in ArraySingleObject obj_id={obj_id}"
                    )
                    reader._offset -= 1
                    break

            sub_records[obj_id] = ObjectArraySubRecord(
                object_id=obj_id,
                length=array_length,
                file_offset=record_offset,
                element_refs=tuple(element_refs),
                field_name=field_name,
            )

        elif rt == RecordType.ARRAY_SINGLE_STRING:
            obj_id = reader.read_int32()
            array_length = reader.read_int32()
            field_name = top_level_refs.get(obj_id)
            element_refs: list[int | None] = []
            for _ in range(array_length):
                if reader._offset >= len(data):
                    break
                elem_rt = RecordType(reader.read_byte())
                if elem_rt == RecordType.BINARY_OBJECT_STRING:
                    s_obj_id = reader.read_int32()
                    s_val = reader.read_length_prefixed_string()
                    sub_records[s_obj_id] = StringSubRecord(
                        object_id=s_obj_id, value=s_val,
                        file_offset=reader._offset, field_name=None,
                    )
                    element_refs.append(s_obj_id)
                elif elem_rt == RecordType.OBJECT_NULL:
                    element_refs.append(None)
                elif elem_rt == RecordType.MEMBER_REFERENCE:
                    element_refs.append(reader.read_int32())
                elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE_256:
                    null_count = reader.read_byte()
                    element_refs.extend([None] * null_count)
                elif elem_rt == RecordType.OBJECT_NULL_MULTIPLE:
                    null_count = reader.read_int32()
                    element_refs.extend([None] * null_count)
                else:
                    warnings.append(
                        f"Unhandled element record {elem_rt.name} in ArraySingleString obj_id={obj_id}"
                    )
                    reader._offset -= 1
                    break
            sub_records[obj_id] = ObjectArraySubRecord(
                object_id=obj_id,
                length=array_length,
                file_offset=record_offset,
                element_refs=tuple(element_refs),
                field_name=field_name,
            )

        elif rt == RecordType.CLASS_WITH_MEMBERS_AND_TYPES:
            reader._offset -= 1  # put back the byte
            _parse_class_with_members_and_types(
                reader, data, sub_records, class_metadata, top_level_refs, warnings,
            )

        elif rt == RecordType.SYSTEM_CLASS_WITH_MEMBERS_AND_TYPES:
            reader._offset -= 1
            _parse_system_class_with_members_and_types(
                reader, data, sub_records, class_metadata, top_level_refs, warnings,
            )

        elif rt == RecordType.SYSTEM_CLASS_WITH_MEMBERS:
            reader._offset -= 1
            _parse_system_class_with_members(
                reader, data, sub_records, class_metadata, top_level_refs, warnings,
            )

        elif rt == RecordType.CLASS_WITH_ID:
            reader._offset -= 1
            _parse_class_with_id(
                reader, data, sub_records, class_metadata, top_level_refs, warnings,
            )

        elif rt == RecordType.BINARY_OBJECT_STRING:
            obj_id = reader.read_int32()
            s_val = reader.read_length_prefixed_string()
            field_name = top_level_refs.get(obj_id)
            sub_records[obj_id] = StringSubRecord(
                object_id=obj_id, value=s_val,
                file_offset=record_offset, field_name=field_name,
            )

        elif rt == RecordType.BINARY_LIBRARY:
            _lib_id2 = reader.read_int32()
            _lib_name2 = reader.read_length_prefixed_string()

        elif rt == RecordType.OBJECT_NULL:
            pass  # standalone null, skip

        elif rt == RecordType.OBJECT_NULL_MULTIPLE_256:
            _count = reader.read_byte()

        elif rt == RecordType.OBJECT_NULL_MULTIPLE:
            _count = reader.read_int32()

        elif rt == RecordType.MEMBER_REFERENCE:
            _ref_id = reader.read_int32()

        elif rt == RecordType.MEMBER_PRIMITIVE_TYPED:
            _pt = PrimitiveType(reader.read_byte())
            _skip_primitive(reader, _pt)

        else:
            warnings.append(f"Unhandled RecordType {rt.name} ({rt.value}) at 0x{record_offset:04X}")
            break

    return SubRecordParseResult(
        top_level_field_names=top_level_refs,
        sub_records=sub_records,
        parse_end_offset=reader._offset,
        total_file_size=len(data),
        warnings=warnings,
    )


def _parse_class_with_members_and_types(
    reader: _BinaryReader,
    data: bytes,
    sub_records: dict[int, SubRecord],
    class_metadata: dict[int, _ClassMetadata],
    top_level_refs: dict[int, str],
    warnings: list[str],
) -> None:
    record_offset = reader._offset
    _rt = RecordType(reader.read_byte())  # consume the record type
    obj_id = reader.read_int32()
    class_name = reader.read_length_prefixed_string()
    mc = reader.read_int32()
    names = [reader.read_length_prefixed_string() for _ in range(mc)]
    btypes = [BinaryType(reader.read_byte()) for _ in range(mc)]
    descs = [
        _FieldDescriptor(name=n, binary_type=b, additional_info=_read_additional_info(reader, b))
        for n, b in zip(names, btypes, strict=True)
    ]
    cls_lib = reader.read_int32()

    # Store metadata for ClassWithId back-references
    class_metadata[obj_id] = _ClassMetadata(
        class_name=class_name,
        descriptors=tuple(descs),
        library_id=cls_lib,
    )

    member_values = {}
    for d in descs:
        member_values[d.name] = _read_top_level_value(reader, d)

    field_name = top_level_refs.get(obj_id)
    sub_records[obj_id] = ClassSubRecord(
        object_id=obj_id,
        class_name=class_name,
        member_names=tuple(names),
        member_values=member_values,
        file_offset=record_offset,
        field_name=field_name,
    )


def _parse_class_with_id(
    reader: _BinaryReader,
    data: bytes,
    sub_records: dict[int, SubRecord],
    class_metadata: dict[int, _ClassMetadata],
    top_level_refs: dict[int, str],
    warnings: list[str],
) -> None:
    record_offset = reader._offset
    _rt = RecordType(reader.read_byte())  # consume the record type
    obj_id = reader.read_int32()
    metadata_id = reader.read_int32()

    meta = class_metadata.get(metadata_id)
    if meta is None:
        warnings.append(
            f"ClassWithId obj_id={obj_id} references unknown metadata_id={metadata_id} at 0x{record_offset:04X}"
        )
        return

    member_values = {}
    for d in meta.descriptors:
        member_values[d.name] = _read_top_level_value(reader, d)

    field_name = top_level_refs.get(obj_id)
    sub_records[obj_id] = ClassSubRecord(
        object_id=obj_id,
        class_name=meta.class_name,
        member_names=tuple(d.name for d in meta.descriptors),
        member_values=member_values,
        file_offset=record_offset,
        field_name=field_name,
    )


def _parse_class_record(
    reader: _BinaryReader,
    rt: RecordType,
    data: bytes,
    sub_records: dict[int, SubRecord],
    class_metadata: dict[int, _ClassMetadata],
    top_level_refs: dict[int, str],
    warnings: list[str],
) -> None:
    """Dispatch a class record parse based on its type."""
    if rt == RecordType.CLASS_WITH_MEMBERS_AND_TYPES:
        _parse_class_with_members_and_types(
            reader, data, sub_records, class_metadata, top_level_refs, warnings,
        )
    elif rt == RecordType.SYSTEM_CLASS_WITH_MEMBERS_AND_TYPES:
        _parse_system_class_with_members_and_types(
            reader, data, sub_records, class_metadata, top_level_refs, warnings,
        )
    elif rt == RecordType.SYSTEM_CLASS_WITH_MEMBERS:
        _parse_system_class_with_members(
            reader, data, sub_records, class_metadata, top_level_refs, warnings,
        )
    elif rt == RecordType.CLASS_WITH_ID:
        _parse_class_with_id(
            reader, data, sub_records, class_metadata, top_level_refs, warnings,
        )


def _parse_system_class_with_members_and_types(
    reader: _BinaryReader,
    data: bytes,
    sub_records: dict[int, SubRecord],
    class_metadata: dict[int, _ClassMetadata],
    top_level_refs: dict[int, str],
    warnings: list[str],
) -> None:
    """Parse SystemClassWithMembersAndTypes — same as ClassWithMembersAndTypes but no library ID."""
    record_offset = reader._offset
    _rt = RecordType(reader.read_byte())  # consume the record type
    obj_id = reader.read_int32()
    class_name = reader.read_length_prefixed_string()
    mc = reader.read_int32()
    names = [reader.read_length_prefixed_string() for _ in range(mc)]
    btypes = [BinaryType(reader.read_byte()) for _ in range(mc)]
    descs = [
        _FieldDescriptor(name=n, binary_type=b, additional_info=_read_additional_info(reader, b))
        for n, b in zip(names, btypes, strict=True)
    ]
    # NO library_id for system classes

    class_metadata[obj_id] = _ClassMetadata(
        class_name=class_name,
        descriptors=tuple(descs),
        library_id=-1,  # sentinel for system class
    )

    member_values = {}
    for d in descs:
        member_values[d.name] = _read_top_level_value(reader, d)

    field_name = top_level_refs.get(obj_id)
    sub_records[obj_id] = ClassSubRecord(
        object_id=obj_id,
        class_name=class_name,
        member_names=tuple(names),
        member_values=member_values,
        file_offset=record_offset,
        field_name=field_name,
    )


def _parse_system_class_with_members(
    reader: _BinaryReader,
    data: bytes,
    sub_records: dict[int, SubRecord],
    class_metadata: dict[int, _ClassMetadata],
    top_level_refs: dict[int, str],
    warnings: list[str],
) -> None:
    """Parse SystemClassWithMembers — member names only, no type info, no library ID."""
    record_offset = reader._offset
    _rt = RecordType(reader.read_byte())
    obj_id = reader.read_int32()
    class_name = reader.read_length_prefixed_string()
    mc = reader.read_int32()
    names = [reader.read_length_prefixed_string() for _ in range(mc)]
    # No binary types or additional info — this record type has no type metadata
    # We can't reliably parse member values without type info, so just record it
    warnings.append(
        f"SystemClassWithMembers obj_id={obj_id} class={class_name} at 0x{record_offset:04X} — "
        f"skipping {mc} untyped members"
    )
    field_name = top_level_refs.get(obj_id)
    sub_records[obj_id] = ClassSubRecord(
        object_id=obj_id,
        class_name=class_name,
        member_names=tuple(names),
        member_values={},
        file_offset=record_offset,
        field_name=field_name,
    )


def _read_primitive_array(
    reader: _BinaryReader,
    prim_type: PrimitiveType,
    count: int,
) -> list[Any]:
    """Read a contiguous array of primitive values."""
    values = []
    for _ in range(count):
        if prim_type == PrimitiveType.BOOLEAN:
            values.append(bool(reader.read_byte()))
        elif prim_type == PrimitiveType.BYTE:
            values.append(reader.read_byte())
        elif prim_type == PrimitiveType.CHAR:
            values.append(chr(reader.read_uint16()))
        elif prim_type == PrimitiveType.INT16:
            values.append(struct.unpack_from("<h", reader._data, reader._offset)[0])
            reader._offset += 2
        elif prim_type == PrimitiveType.INT32:
            values.append(reader.read_int32())
        elif prim_type == PrimitiveType.INT64:
            values.append(reader.read_int64())
        elif prim_type == PrimitiveType.SINGLE:
            values.append(reader.read_float32())
        elif prim_type == PrimitiveType.DOUBLE:
            values.append(reader.read_float64())
        elif prim_type == PrimitiveType.DATETIME:
            raw = reader.read_int64()
            ticks = (raw & 0xFFFFFFFFFFFFFFFF) & DOTNET_TICKS_MASK
            try:
                values.append(DOTNET_BASE_DATETIME + timedelta(microseconds=ticks / 10))
            except (OverflowError, ValueError):
                values.append(None)
        elif prim_type == PrimitiveType.TIMESPAN:
            values.append(timedelta(microseconds=reader.read_int64() / 10))
        elif prim_type == PrimitiveType.UINT16:
            values.append(reader.read_uint16())
        elif prim_type == PrimitiveType.UINT32:
            values.append(reader.read_uint32())
        elif prim_type == PrimitiveType.UINT64:
            values.append(reader.read_uint64())
        elif prim_type == PrimitiveType.SBYTE:
            values.append(struct.unpack_from("<b", reader._data, reader._offset)[0])
            reader._offset += 1
        else:
            break
    return values


def _skip_primitive(reader: _BinaryReader, prim_type: PrimitiveType) -> None:
    """Skip one primitive value."""
    size = PRIMITIVE_SIZES.get(prim_type, 0)
    reader._offset += size


def render_sub_record_report(result: SubRecordParseResult) -> str:
    """Render a human-readable report of all parsed sub-records."""
    lines = []
    lines.append(f"Sub-record parse: {len(result.sub_records)} records, "
                  f"parsed to 0x{result.parse_end_offset:04X} / 0x{result.total_file_size:04X} "
                  f"({result.parse_end_offset / result.total_file_size * 100:.1f}%)")
    if result.warnings:
        lines.append(f"Warnings: {len(result.warnings)}")
        for w in result.warnings:
            lines.append(f"  ! {w}")
    lines.append("")

    for obj_id in sorted(result.sub_records.keys()):
        rec = result.sub_records[obj_id]
        fname = rec.field_name or "???"

        if isinstance(rec, ArraySubRecord):
            # Show first few values
            preview = ", ".join(str(v) for v in rec.values[:5])
            if rec.length > 5:
                preview += f", ... ({rec.length} total)"
            lines.append(
                f"  ref {obj_id:3d}  {rec.primitive_type.name:10s}[{rec.length:4d}]  "
                f"payload@0x{rec.payload_file_offset:04X}  ({rec.payload_byte_length:5d} bytes)  "
                f"field={fname}"
            )
            lines.append(f"           values=[{preview}]")

        elif isinstance(rec, RectangularArraySubRecord):
            dims = "x".join(str(d) for d in rec.dimensions)
            lines.append(
                f"  ref {obj_id:3d}  {rec.primitive_type.name:10s}[{dims}]  "
                f"payload@0x{rec.payload_file_offset:04X}  ({rec.payload_byte_length:5d} bytes)  "
                f"field={fname}"
            )

        elif isinstance(rec, StringSubRecord):
            lines.append(
                f"  ref {obj_id:3d}  String           "
                f"@0x{rec.file_offset:04X}  "
                f"value={rec.value[:60]!r}  field={fname}"
            )

        elif isinstance(rec, ClassSubRecord):
            lines.append(
                f"  ref {obj_id:3d}  Class            "
                f"@0x{rec.file_offset:04X}  "
                f"class={rec.class_name}  members={len(rec.member_names)}  field={fname}"
            )

        elif isinstance(rec, ObjectArraySubRecord):
            non_null = sum(1 for r in rec.element_refs if r is not None)
            lines.append(
                f"  ref {obj_id:3d}  Object[]         "
                f"@0x{rec.file_offset:04X}  "
                f"len={rec.length}  non_null={non_null}  field={fname}"
            )

    return "\n".join(lines)

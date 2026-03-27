"""Probe the BinaryFormatter stream after top-level parse to understand sub-record layout."""
import struct
from pathlib import Path

# Re-use the parser's reader to advance past the top-level record,
# then inspect what follows.
from ipm_bot.save.parser import (
    _BinaryReader, _parse_raw_player_data, RecordType, PrimitiveType,
    BinaryType, _read_additional_info, _read_top_level_value, _FieldDescriptor,
)

DATA_PATH = Path(r"C:\dev\ipm-bot\data\artifacts\snapshots\2026-03-24T02-19-33-788532Z_snapshot_com.TironiumTech.IdlePlanetMiner\extracted\external_sdcard\files\playerInfo.dat")

data = DATA_PATH.read_bytes()
print(f"File size: {len(data)} bytes")

# Parse top-level to consume the header + all 478 members, then note the offset
reader = _BinaryReader(data)

# Header
record_type = RecordType(reader.read_byte())
assert record_type == RecordType.SERIALIZED_STREAM_HEADER
_root_id = reader.read_int32()
_header_id = reader.read_int32()
_major = reader.read_int32()
_minor = reader.read_int32()

# BinaryLibrary
lib_record = RecordType(reader.read_byte())
assert lib_record == RecordType.BINARY_LIBRARY
_lib_id = reader.read_int32()
_assembly = reader.read_length_prefixed_string()
print(f"Assembly: {_assembly}")

# Root class record
root_record = RecordType(reader.read_byte())
assert root_record == RecordType.CLASS_WITH_MEMBERS_AND_TYPES
_obj_id = reader.read_int32()
_class_name = reader.read_length_prefixed_string()
member_count = reader.read_int32()
print(f"Root class: {_class_name}, members: {member_count}")

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

print(f"Header parsed, offset after class metadata: 0x{reader._offset:04X}")

# Now read all 478 member values, tracking MemberReferences
refs = {}
for desc in descriptors:
    value = _read_top_level_value(reader, desc)
    # Check if it's a MemberReference
    if hasattr(value, 'object_id'):
        refs[desc.name] = value.object_id

print(f"Top-level values parsed, offset after values: 0x{reader._offset:04X}")
print(f"MemberReference count: {len(refs)}")

# Now scan the sub-records
print(f"\n{'='*80}")
print(f"SUB-RECORDS starting at offset 0x{reader._offset:04X}")
print(f"{'='*80}\n")

count = 0
while reader._offset < len(data):
    record_offset = reader._offset
    try:
        rt = RecordType(reader.read_byte())
    except (ValueError, IndexError):
        print(f"  0x{record_offset:04X}: UNKNOWN byte 0x{data[record_offset]:02X}")
        break

    if rt == RecordType.MESSAGE_END:
        print(f"  0x{record_offset:04X}: MessageEnd")
        break
    elif rt == RecordType.ARRAY_SINGLE_PRIMITIVE:
        obj_id = reader.read_int32()
        array_length = reader.read_int32()
        prim_type = PrimitiveType(reader.read_byte())
        payload_offset = reader._offset

        # Compute element size
        elem_sizes = {
            PrimitiveType.BOOLEAN: 1,
            PrimitiveType.BYTE: 1,
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
        }
        elem_size = elem_sizes.get(prim_type, 0)
        payload_bytes = array_length * elem_size

        # Find which field this ref belongs to
        field_name = "???"
        for fname, ref_id in refs.items():
            if ref_id == obj_id:
                field_name = fname
                break

        print(f"  0x{record_offset:04X}: ArraySinglePrimitive  obj_id={obj_id:3d}  len={array_length:4d}  type={prim_type.name:10s}  payload@0x{payload_offset:04X}  ({payload_bytes} bytes)  field={field_name}")
        
        # Skip the payload
        reader._offset += payload_bytes

    elif rt == RecordType.BINARY_LIBRARY:
        lib_id = reader.read_int32()
        lib_name = reader.read_length_prefixed_string()
        print(f"  0x{record_offset:04X}: BinaryLibrary  id={lib_id}  name={lib_name}")

    elif rt == RecordType.CLASS_WITH_MEMBERS_AND_TYPES:
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

        field_name = "???"
        for fname, ref_id in refs.items():
            if ref_id == obj_id:
                field_name = fname
                break

        print(f"  0x{record_offset:04X}: ClassWithMembersAndTypes  obj_id={obj_id:3d}  class={class_name}  members={mc}  field={field_name}")
        print(f"          member_names={names[:5]}{'...' if mc > 5 else ''}")

        # Read values for these members
        for d in descs:
            _read_top_level_value(reader, d)

    elif rt == RecordType.CLASS_WITH_ID:
        obj_id = reader.read_int32()
        metadata_id = reader.read_int32()
        print(f"  0x{record_offset:04X}: ClassWithId  obj_id={obj_id:3d}  metadata_ref={metadata_id}")
        # Would need to replay the member reads from the referenced class definition
        # For now, skip - we'll handle this properly in the real parser
        print(f"          (skipping member values - needs metadata lookup)")
        break  # Can't continue without metadata

    elif rt == RecordType.BINARY_OBJECT_STRING:
        obj_id = reader.read_int32()
        s = reader.read_length_prefixed_string()
        field_name = "???"
        for fname, ref_id in refs.items():
            if ref_id == obj_id:
                field_name = fname
                break
        print(f"  0x{record_offset:04X}: BinaryObjectString  obj_id={obj_id:3d}  value={s[:60]!r}  field={field_name}")

    elif rt == RecordType.MEMBER_REFERENCE:
        ref_id = reader.read_int32()
        print(f"  0x{record_offset:04X}: MemberReference  ref_id={ref_id}")

    elif rt == RecordType.OBJECT_NULL:
        print(f"  0x{record_offset:04X}: ObjectNull")

    elif rt == RecordType.ARRAY_SINGLE_OBJECT:
        obj_id = reader.read_int32()
        array_length = reader.read_int32()
        print(f"  0x{record_offset:04X}: ArraySingleObject  obj_id={obj_id:3d}  len={array_length}")
        # Elements follow as individual records

    elif rt == RecordType.BINARY_ARRAY:
        obj_id = reader.read_int32()
        array_type = reader.read_byte()
        rank = reader.read_int32()
        lengths = [reader.read_int32() for _ in range(rank)]
        # additional info depends on array_type...
        print(f"  0x{record_offset:04X}: BinaryArray  obj_id={obj_id:3d}  array_type={array_type}  rank={rank}  lengths={lengths}")
        # Complex - skip for probe
        break
    
    elif rt == RecordType.OBJECT_NULL_MULTIPLE_256:
        null_count = reader.read_byte()
        print(f"  0x{record_offset:04X}: ObjectNullMultiple256  count={null_count}")

    elif rt == RecordType.OBJECT_NULL_MULTIPLE:
        null_count = reader.read_int32()
        print(f"  0x{record_offset:04X}: ObjectNullMultiple  count={null_count}")
    
    elif rt == RecordType.MEMBER_PRIMITIVE_TYPED:
        pt = PrimitiveType(reader.read_byte())
        print(f"  0x{record_offset:04X}: MemberPrimitiveTyped  type={pt.name}")
        # skip value
        break

    else:
        print(f"  0x{record_offset:04X}: UNHANDLED RecordType={rt.name} ({rt.value})")
        break

    count += 1
    if count > 300:
        print(f"  ... stopped after 300 records (offset now at 0x{reader._offset:04X})")
        break

print(f"\nFinal offset: 0x{reader._offset:04X} / 0x{len(data):04X}")

"""Minimal raw save parser for top-level SaveLoad.PlayerData fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
import json
from pathlib import Path
import struct
from typing import Any, Mapping

from .exceptions import (
    FieldDecodeError,
    UnsupportedSaveFormatError,
    UnsupportedTopLevelRecordError,
)
from .models import (
    AdState,
    CurrencyState,
    EventState,
    PlayerProgressState,
    PlayerSnapshot,
    SaveMetadata,
)


class RecordType(IntEnum):
    SERIALIZED_STREAM_HEADER = 0
    CLASS_WITH_ID = 1
    SYSTEM_CLASS_WITH_MEMBERS = 2
    CLASS_WITH_MEMBERS = 3
    SYSTEM_CLASS_WITH_MEMBERS_AND_TYPES = 4
    CLASS_WITH_MEMBERS_AND_TYPES = 5
    BINARY_OBJECT_STRING = 6
    BINARY_ARRAY = 7
    MEMBER_PRIMITIVE_TYPED = 8
    MEMBER_REFERENCE = 9
    OBJECT_NULL = 10
    MESSAGE_END = 11
    BINARY_LIBRARY = 12
    OBJECT_NULL_MULTIPLE_256 = 13
    OBJECT_NULL_MULTIPLE = 14
    ARRAY_SINGLE_PRIMITIVE = 15
    ARRAY_SINGLE_OBJECT = 16
    ARRAY_SINGLE_STRING = 17


class BinaryType(IntEnum):
    PRIMITIVE = 0
    STRING = 1
    OBJECT = 2
    SYSTEM_CLASS = 3
    CLASS = 4
    OBJECT_ARRAY = 5
    STRING_ARRAY = 6
    PRIMITIVE_ARRAY = 7


class PrimitiveType(IntEnum):
    BOOLEAN = 1
    BYTE = 2
    CHAR = 3
    DECIMAL = 5
    DOUBLE = 6
    INT16 = 7
    INT32 = 8
    INT64 = 9
    SBYTE = 10
    SINGLE = 11
    TIMESPAN = 12
    DATETIME = 13
    UINT16 = 14
    UINT32 = 15
    UINT64 = 16


DOTNET_TICKS_MASK = 0x3FFFFFFFFFFFFFFF
DOTNET_BASE_DATETIME = datetime(1, 1, 1)
RAW_PLAYER_DATA_HEADER = b"\x00\x01\x00\x00\x00\xff\xff\xff\xff"


@dataclass(frozen=True, slots=True)
class _MemberReference:
    object_id: int


@dataclass(frozen=True, slots=True)
class _NullRun:
    count: int


@dataclass(frozen=True, slots=True)
class _FieldDescriptor:
    name: str
    binary_type: BinaryType
    additional_info: PrimitiveType | str | tuple[str, int] | None


@dataclass(frozen=True, slots=True)
class _TopLevelParse:
    values: dict[str, Any]
    top_level_member_count: int


class _BinaryReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def read_byte(self) -> int:
        value = self._data[self._offset]
        self._offset += 1
        return value

    def read_int32(self) -> int:
        value = struct.unpack_from("<i", self._data, self._offset)[0]
        self._offset += 4
        return value

    def read_int64(self) -> int:
        value = struct.unpack_from("<q", self._data, self._offset)[0]
        self._offset += 8
        return value

    def read_uint16(self) -> int:
        value = struct.unpack_from("<H", self._data, self._offset)[0]
        self._offset += 2
        return value

    def read_uint32(self) -> int:
        value = struct.unpack_from("<I", self._data, self._offset)[0]
        self._offset += 4
        return value

    def read_uint64(self) -> int:
        value = struct.unpack_from("<Q", self._data, self._offset)[0]
        self._offset += 8
        return value

    def read_float32(self) -> float:
        value = struct.unpack_from("<f", self._data, self._offset)[0]
        self._offset += 4
        return value

    def read_float64(self) -> float:
        value = struct.unpack_from("<d", self._data, self._offset)[0]
        self._offset += 8
        return value

    def read_length_prefixed_string(self) -> str:
        length = 0
        shift = 0
        while True:
            current = self.read_byte()
            length |= (current & 0x7F) << shift
            if not (current & 0x80):
                break
            shift += 7
        end = self._offset + length
        text = self._data[self._offset : end].decode("utf-8", errors="replace")
        self._offset = end
        return text


def extract_top_level_values(source: str | Path | bytes | Mapping[str, Any]) -> dict[str, Any]:
    """Extract top-level PlayerData fields without mapping them into a snapshot."""

    parsed = _load_source_values(source)
    return {
        key: _to_public_value(value)
        for key, value in parsed.values.items()
    }


def parse_player_snapshot(
    source: str | Path | bytes | Mapping[str, Any],
) -> PlayerSnapshot:
    """Parse a save source into a normalized, read-only snapshot."""

    parsed = _load_source_values(source)
    values = parsed.values
    source_path = str(Path(source).resolve()) if isinstance(source, (str, Path)) else None
    source_format = _detect_source_format(source)

    unresolved_references = {
        key: value.object_id
        for key, value in values.items()
        if isinstance(value, _MemberReference)
    }
    free_rewards_claimed = _extract_reward_claim_list(source, values, "freeRewardsClaimed")
    miner_pass_rewards_claimed = _extract_reward_claim_list(
        source,
        values,
        "minerPassRewardsClaimed",
    )

    currencies = CurrencyState(
        cash=_expect_type(values, "cash", float),
        dark_matter=_expect_type(values, "darkMatter", int),
        energy_cell=_expect_type(values, "energyCell", int),
        holo_bolts=_expect_type(values, "holoBolts", int),
        prestige_currency=_expect_type(values, "prestigeCurrency", int),
    )
    ad = AdState(
        ad_boost_active=_expect_type(values, "adBoostActive", bool),
        ad_boost_start_date=_expect_type(values, "adBoostStartDate", datetime),
        last_ad_watched_date=_expect_type(values, "lastAdWatchedDate", datetime),
        ads_watched=_expect_type(values, "adsWatched", int),
        arks_claimed=_expect_type(values, "arksClaimed", int),
        pending_reward_type=_expect_type(values, "pendingRewardType", int),
        reward_is_dark_matter=_expect_type(values, "rewardIsDarkMatterBool", bool),
        ark_reward_ready_to_claim=_expect_type(
            values, "arkRewardReadyToClaim", bool
        ),
        daily_gift_ready=_expect_type(values, "dailyGiftReadyBool", bool),
        daily_gift_ad_watched=_expect_type(
            values, "dailyGiftAdWatchedBool", bool
        ),
    )
    event = EventState(
        event_mission_showed=_expect_type(values, "eventMissionShowed", bool),
        is_local_event_running=_expect_type(values, "isLocalEventRunning", bool),
        local_event_id=_expect_type(values, "localEventId", int),
        local_event_close_time=_expect_type(values, "localEventCloseTime", datetime),
        last_closed_local_event_global_id=_expect_type(
            values, "lastClosedLocalEventGlobalId", str
        ),
        last_miner_pass_owned=_expect_type(values, "lastMinerPassOwned", int),
        is_miner_pass_activated=_expect_type(values, "isMinerPassActivated", bool),
        free_rewards_claimed_count=_count_claimed_rewards(free_rewards_claimed),
        free_rewards_total_count=_count_total_rewards(free_rewards_claimed),
        miner_pass_rewards_claimed_count=_count_claimed_rewards(
            miner_pass_rewards_claimed
        ),
        miner_pass_rewards_total_count=_count_total_rewards(
            miner_pass_rewards_claimed
        ),
        free_rewards_claimed_ref=unresolved_references.get("freeRewardsClaimed"),
        miner_pass_rewards_claimed_ref=unresolved_references.get(
            "minerPassRewardsClaimed"
        ),
    )
    metadata = SaveMetadata(
        save_timestamp=_expect_type(values, "saveTimestamp", datetime),
        initial_data_uploaded_to_firestore=_expect_type(
            values, "initialDataUploadedToFirestore", bool
        ),
        corrupted_data_uploaded_on_playfab=_expect_type(
            values, "corruptedDataUploadedOnPlayfab", bool
        ),
        source_path=source_path,
        source_format=source_format,
        top_level_member_count=parsed.top_level_member_count,
    )
    player = PlayerProgressState(
        player_level=_expect_type(values, "playerLevel", int),
        player_xp=_expect_type(values, "playerXP", int),
    )

    return PlayerSnapshot(
        currencies=currencies,
        ad=ad,
        event=event,
        metadata=metadata,
        player=player,
        raw_fields=dict(values),
        unresolved_references=unresolved_references,
    )


def _load_source_values(source: str | Path | bytes | Mapping[str, Any]) -> _TopLevelParse:
    if isinstance(source, Mapping):
        return _TopLevelParse(values=dict(source), top_level_member_count=len(source))

    if isinstance(source, bytes):
        return _parse_raw_player_data(source)

    path = Path(source)
    data = path.read_bytes()
    if data.startswith(RAW_PLAYER_DATA_HEADER):
        return _parse_raw_player_data(data)

    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnsupportedSaveFormatError(
            f"Unsupported save format for {path}: expected raw playerInfo.dat or JSON."
        ) from exc

    if not isinstance(decoded, dict):
        raise UnsupportedSaveFormatError(
            f"Unsupported JSON save shape for {path}: expected an object mapping."
        )

    return _TopLevelParse(values=decoded, top_level_member_count=len(decoded))


def _detect_source_format(source: str | Path | bytes | Mapping[str, Any]) -> str:
    if isinstance(source, Mapping):
        return "mapping"
    if isinstance(source, bytes):
        return "binaryformatter-playerdata"
    path = Path(source)
    if path.suffix.lower() == ".json":
        return "json"
    return "binaryformatter-playerdata"


def _extract_reward_claim_list(
    source: str | Path | bytes | Mapping[str, Any],
    values: Mapping[str, Any],
    field_name: str,
) -> tuple[bool, ...] | None:
    direct_value = values.get(field_name)
    direct_list = _coerce_bool_list(direct_value)
    if direct_list is not None:
        return direct_list
    if not isinstance(source, (str, Path, bytes)):
        return None
    try:
        from .sub_records import ArraySubRecord, ClassSubRecord, parse_sub_records
    except Exception:
        return None
    try:
        result = parse_sub_records(source)
    except Exception:
        return None

    object_id = None
    for ref_object_id, ref_field_name in result.top_level_field_names.items():
        if ref_field_name == field_name:
            object_id = ref_object_id
            break
    if object_id is None:
        return None

    def _resolve_bool_list(record_object_id: int) -> tuple[bool, ...] | None:
        record = result.sub_records.get(record_object_id)
        if record is None:
            return None
        if isinstance(record, ArraySubRecord):
            return tuple(bool(value) for value in record.values)
        if isinstance(record, ClassSubRecord):
            size = _extract_int_member(record.member_values, "_size", "size")
            items_object_id = _extract_ref_object_id(
                record.member_values.get("_items"),
                record.member_values.get("items"),
            )
            if items_object_id is None:
                return None
            resolved_items = _resolve_bool_list(items_object_id)
            if resolved_items is None:
                return None
            if size is None:
                return resolved_items
            return resolved_items[:size]
        return None

    return _resolve_bool_list(object_id)


def _coerce_bool_list(value: Any) -> tuple[bool, ...] | None:
    if not isinstance(value, list):
        return None
    if any(not isinstance(item, bool) for item in value):
        return None
    return tuple(value)


def _extract_int_member(member_values: Mapping[str, Any], *field_names: str) -> int | None:
    for field_name in field_names:
        value = member_values.get(field_name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _extract_ref_object_id(*values: Any) -> int | None:
    for value in values:
        object_id = getattr(value, "object_id", None)
        if isinstance(object_id, int):
            return object_id
    return None


def _count_claimed_rewards(values: tuple[bool, ...] | None) -> int | None:
    if values is None:
        return None
    return sum(1 for value in values if value)


def _count_total_rewards(values: tuple[bool, ...] | None) -> int | None:
    if values is None:
        return None
    return len(values)


def _parse_raw_player_data(data: bytes) -> _TopLevelParse:
    reader = _BinaryReader(data)

    header_record = RecordType(reader.read_byte())
    if header_record is not RecordType.SERIALIZED_STREAM_HEADER:
        raise UnsupportedSaveFormatError(
            f"Expected SerializedStreamHeader, got record type {header_record!r}."
        )

    _root_id = reader.read_int32()
    _header_id = reader.read_int32()
    _major_version = reader.read_int32()
    _minor_version = reader.read_int32()

    library_record = RecordType(reader.read_byte())
    if library_record is not RecordType.BINARY_LIBRARY:
        raise UnsupportedSaveFormatError(
            f"Expected BinaryLibrary after header, got record type {library_record!r}."
        )

    _library_id = reader.read_int32()
    assembly_name = reader.read_length_prefixed_string()
    if "Assembly-CSharp" not in assembly_name:
        raise UnsupportedSaveFormatError(
            f"Unexpected library name {assembly_name!r}; expected Assembly-CSharp."
        )

    root_record = RecordType(reader.read_byte())
    if root_record is not RecordType.CLASS_WITH_MEMBERS_AND_TYPES:
        raise UnsupportedSaveFormatError(
            "The root record is not ClassWithMembersAndTypes; "
            "this parser only supports the validated PlayerData stream shape."
        )

    _object_id = reader.read_int32()
    class_name = reader.read_length_prefixed_string()
    if class_name != "SaveLoad+PlayerData":
        raise UnsupportedSaveFormatError(
            f"Unexpected root class {class_name!r}; expected SaveLoad+PlayerData."
        )

    member_count = reader.read_int32()
    member_names = [reader.read_length_prefixed_string() for _ in range(member_count)]
    binary_types = [BinaryType(reader.read_byte()) for _ in range(member_count)]
    descriptors = [
        _FieldDescriptor(
            name=name,
            binary_type=binary_type,
            additional_info=_read_additional_info(reader, binary_type),
        )
        for name, binary_type in zip(member_names, binary_types, strict=True)
    ]
    _class_library_id = reader.read_int32()

    values: dict[str, Any] = {}
    for descriptor in descriptors:
        values[descriptor.name] = _read_top_level_value(reader, descriptor)

    return _TopLevelParse(values=values, top_level_member_count=member_count)


def _read_additional_info(
    reader: _BinaryReader,
    binary_type: BinaryType,
) -> PrimitiveType | str | tuple[str, int] | None:
    if binary_type is BinaryType.PRIMITIVE:
        return PrimitiveType(reader.read_byte())
    if binary_type is BinaryType.SYSTEM_CLASS:
        return reader.read_length_prefixed_string()
    if binary_type is BinaryType.CLASS:
        return (reader.read_length_prefixed_string(), reader.read_int32())
    if binary_type is BinaryType.PRIMITIVE_ARRAY:
        return PrimitiveType(reader.read_byte())
    return None


def _read_top_level_value(reader: _BinaryReader, descriptor: _FieldDescriptor) -> Any:
    if descriptor.binary_type is BinaryType.PRIMITIVE:
        primitive_type = descriptor.additional_info
        if not isinstance(primitive_type, PrimitiveType):
            raise UnsupportedTopLevelRecordError(
                f"Primitive field {descriptor.name} is missing its primitive type."
            )
        return _read_primitive_value(reader, primitive_type)

    record_type = RecordType(reader.read_byte())

    if record_type is RecordType.MEMBER_REFERENCE:
        return _MemberReference(reader.read_int32())
    if record_type is RecordType.OBJECT_NULL:
        return None
    if record_type is RecordType.BINARY_OBJECT_STRING:
        _object_id = reader.read_int32()
        return reader.read_length_prefixed_string()
    if record_type is RecordType.OBJECT_NULL_MULTIPLE_256:
        return _NullRun(reader.read_byte())
    if record_type is RecordType.OBJECT_NULL_MULTIPLE:
        return _NullRun(reader.read_int32())
    if record_type is RecordType.MEMBER_PRIMITIVE_TYPED:
        primitive_type = PrimitiveType(reader.read_byte())
        return _read_primitive_value(reader, primitive_type)

    raise UnsupportedTopLevelRecordError(
        f"Top-level field {descriptor.name!r} used unsupported record type {record_type}."
    )


def _read_primitive_value(
    reader: _BinaryReader,
    primitive_type: PrimitiveType,
) -> Any:
    if primitive_type is PrimitiveType.BOOLEAN:
        return bool(reader.read_byte())
    if primitive_type is PrimitiveType.BYTE:
        return reader.read_byte()
    if primitive_type is PrimitiveType.CHAR:
        return chr(reader.read_uint16())
    if primitive_type is PrimitiveType.DOUBLE:
        return reader.read_float64()
    if primitive_type is PrimitiveType.INT16:
        value = struct.unpack_from("<h", reader._data, reader._offset)[0]
        reader._offset += 2
        return value
    if primitive_type is PrimitiveType.INT32:
        return reader.read_int32()
    if primitive_type is PrimitiveType.INT64:
        return reader.read_int64()
    if primitive_type is PrimitiveType.SBYTE:
        value = struct.unpack_from("<b", reader._data, reader._offset)[0]
        reader._offset += 1
        return value
    if primitive_type is PrimitiveType.SINGLE:
        return reader.read_float32()
    if primitive_type is PrimitiveType.TIMESPAN:
        return timedelta(microseconds=reader.read_int64() / 10)
    if primitive_type is PrimitiveType.DATETIME:
        return _decode_dotnet_datetime(reader.read_int64())
    if primitive_type is PrimitiveType.UINT16:
        return reader.read_uint16()
    if primitive_type is PrimitiveType.UINT32:
        return reader.read_uint32()
    if primitive_type is PrimitiveType.UINT64:
        return reader.read_uint64()

    raise UnsupportedTopLevelRecordError(
        f"Unsupported primitive type in PlayerData stream: {primitive_type}."
    )


def _decode_dotnet_datetime(raw_value: int) -> datetime:
    ticks = (raw_value & 0xFFFFFFFFFFFFFFFF) & DOTNET_TICKS_MASK
    return DOTNET_BASE_DATETIME + timedelta(microseconds=ticks / 10)


def _expect_type(
    values: Mapping[str, Any],
    field_name: str,
    expected_type: type[Any],
) -> Any:
    value = values.get(field_name)
    if value is None:
        return None
    if isinstance(value, (_MemberReference, _NullRun)):
        return None
    if expected_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if expected_type is float and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, expected_type):
        return value
    raise FieldDecodeError(
        f"Field {field_name!r} expected {expected_type.__name__}, got {type(value).__name__}."
    )


def _to_public_value(value: Any) -> Any:
    if isinstance(value, _MemberReference):
        return {"$ref": value.object_id}
    if isinstance(value, _NullRun):
        return {"$null_count": value.count}
    return value

from pathlib import Path
import struct
import sys
import zlib

CRC_SEED = 0x41916EBD


def read_fstring(data, offset):
    length = struct.unpack_from("<i", data, offset)[0]
    offset += 4

    if length <= 0:
        raise ValueError("Unsupported FString")

    value = data[offset:offset + length - 1].decode("utf-8")
    offset += length

    return value, offset


def parse_property(data, offset):
    start = offset

    name, offset = read_fstring(data, offset)

    if name == "None":
        return {
            "name": name,
            "start": start,
            "end": offset,
        }

    prop_type, offset = read_fstring(data, offset)

    parameter_count = struct.unpack_from("<i", data, offset)[0]
    offset += 4

    parameters = []

    for _ in range(parameter_count):
        parameter_type, offset = read_fstring(data, offset)

        nested_parameter_count = struct.unpack_from("<i", data, offset)[0]
        offset += 4

        if nested_parameter_count != 0:
            raise ValueError("Nested property parameters are not supported")

        parameters.append(parameter_type)

    value_size = struct.unpack_from("<i", data, offset)[0]
    size_offset = offset
    offset += 4

    has_guid = data[offset]
    offset += 1

    if has_guid:
        offset += 16

    value_offset = offset
    end = value_offset + value_size

    return {
        "name": name,
        "type": prop_type,
        "parameters": parameters,
        "size": value_size,
        "size_offset": size_offset,
        "value_offset": value_offset,
        "start": start,
        "end": end,
    }


def find_property(data, target_name, start=0):
    marker = target_name.encode("utf-8") + b"\x00"
    search_offset = start

    while True:
        pos = data.find(marker, search_offset)

        if pos == -1:
            raise ValueError(f"Property not found: {target_name}")

        possible_start = pos - 4

        if possible_start >= 0:
            try:
                prop = parse_property(data, possible_start)

                if prop["name"] == target_name:
                    return prop

            except Exception:
                pass

        search_offset = pos + 1


def main():
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} Campaign.sav NEW_MRP")
        sys.exit(1)

    save_path = Path(sys.argv[1])
    new_mrp = int(sys.argv[2])

    data = bytearray(save_path.read_bytes())

    # Backup
    backup_path = save_path.with_suffix(save_path.suffix + ".bak")

    if not backup_path.exists():
        backup_path.write_bytes(data)
        print(f"Backup: {backup_path}")

    # Find PackedData
    packed = find_property(data, "PackedData")

    if packed["type"] != "ArrayProperty":
        raise ValueError("PackedData is not ArrayProperty")

    if packed["parameters"] != ["ByteProperty"]:
        raise ValueError("PackedData is not ArrayProperty<ByteProperty>")

    # ArrayProperty value begins with uint32 element count
    packed_count_offset = packed["value_offset"]

    packed_count = struct.unpack_from(
        "<I",
        data,
        packed_count_offset
    )[0]

    packed_data_start = packed_count_offset + 4
    packed_data_end = packed_data_start + packed_count

    print("PackedData start:", hex(packed_data_start))
    print("PackedData end:  ", hex(packed_data_end))
    print("PackedData size: ", packed_count)

    # Find CurrentMRP inside PackedData
    current_mrp = find_property(
        data,
        "CurrentMRP",
        packed_data_start
    )

    if current_mrp["start"] >= packed_data_end:
        raise ValueError("CurrentMRP is outside PackedData")

    if current_mrp["type"] != "UInt64Property":
        raise ValueError(
            f"Unexpected CurrentMRP type: {current_mrp['type']}"
        )

    if current_mrp["size"] != 8:
        raise ValueError(
            f"Unexpected CurrentMRP size: {current_mrp['size']}"
        )

    old_mrp = struct.unpack_from(
        "<Q",
        data,
        current_mrp["value_offset"]
    )[0]

    print("CurrentMRP offset:", hex(current_mrp["value_offset"]))
    print("Old MRP:", old_mrp)

    # Find checksum
    checksum = find_property(
        data,
        "Checksum",
        packed_data_end
    )

    if checksum["type"] != "UInt32Property":
        raise ValueError(
            f"Unexpected Checksum type: {checksum['type']}"
        )

    if checksum["size"] != 4:
        raise ValueError(
            f"Unexpected Checksum size: {checksum['size']}"
        )

    stored_checksum = struct.unpack_from(
        "<I",
        data,
        checksum["value_offset"]
    )[0]

    # Verify original checksum first
    calculated_checksum = zlib.crc32(
        data[packed_data_start:packed_data_end],
        CRC_SEED
    ) & 0xFFFFFFFF

    print(f"Stored checksum:     0x{stored_checksum:08X}")
    print(f"Calculated checksum: 0x{calculated_checksum:08X}")

    if stored_checksum != calculated_checksum:
        raise ValueError(
            "Original checksum does not match. "
            "The script will not modify the save."
        )

    # Modify CurrentMRP
    struct.pack_into(
        "<Q",
        data,
        current_mrp["value_offset"],
        new_mrp
    )

    # Recalculate checksum
    new_checksum = zlib.crc32(
        data[packed_data_start:packed_data_end],
        CRC_SEED
    ) & 0xFFFFFFFF

    # Write checksum
    struct.pack_into(
        "<I",
        data,
        checksum["value_offset"],
        new_checksum
    )

    save_path.write_bytes(data)

    print()
    print("New MRP:", new_mrp)
    print(f"New checksum: 0x{new_checksum:08X}")
    print("Saved:", save_path)


if __name__ == "__main__":
    main()
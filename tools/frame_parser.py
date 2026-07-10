"""通信协议帧解析（被 frame_parser 工具调用）。

输入：argv[1] 为 JSON 字符串，字段：
    hex_data: str         — 十六进制帧数据（无 0x 前缀/空格）
    format: str           — auto|ethernet|tlv|custom，默认 auto
    custom_spec: str?     — 自定义帧格式 JSON（format=custom 时使用）
    endian: str           — big|little，默认 big
输出：帧解析文本报告（字段名、偏移、值、校验结果）。
"""
import json
import struct
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    """标准 CRC-32 (Ethernet)。"""
    import binascii
    return binascii.crc32(data) & 0xFFFFFFFF


def parse_ethernet(raw: bytes) -> None:
    if len(raw) < 14:
        print("错误：数据长度不足 14 字节，无法解析为 Ethernet II 帧。")
        return

    dst_mac = ":".join(f"{b:02X}" for b in raw[0:6])
    src_mac = ":".join(f"{b:02X}" for b in raw[6:12])
    ether_type = struct.unpack("!H", raw[12:14])[0]
    payload = raw[14:]

    etype_names = {
        0x0800: "IPv4", 0x0806: "ARP", 0x86DD: "IPv6",
        0x8100: "802.1Q VLAN", 0x88CC: "LLDP",
    }

    print("=== Ethernet II 帧解析 ===")
    print(f"目的 MAC     : {dst_mac}")
    print(f"源 MAC       : {src_mac}")
    print(f"EtherType    : 0x{ether_type:04X} ({etype_names.get(ether_type, '未知')})")
    print(f"载荷长度     : {len(payload)} 字节")
    if len(payload) <= 64:
        print(f"载荷 (hex)   : {payload.hex().upper()}")
    else:
        print(f"载荷前 64B   : {payload[:64].hex().upper()}...")

    # FCS 校验（如果帧尾有 4 字节 FCS）
    if len(raw) >= 18:
        frame_without_fcs = raw[:-4]
        fcs_bytes = raw[-4:]
        computed_fcs = crc32(frame_without_fcs)
        received_fcs = struct.unpack("!I", fcs_bytes)[0]
        if computed_fcs == received_fcs:
            print(f"FCS 校验     : 通过 (0x{received_fcs:08X})")
        else:
            print(f"FCS 校验     : 注意 — 未匹配或帧不含 FCS")


def parse_tlv(raw: bytes, endian: str) -> None:
    print("=== TLV 帧解析 ===")
    print(f"总长度       : {len(raw)} 字节")
    print(f"字节序       : {endian}")
    print()

    fmt_type = ">B" if endian == "big" else "<B"
    fmt_len = ">H" if endian == "big" else "<H"
    offset = 0
    idx = 1

    while offset < len(raw):
        if offset + 3 > len(raw):
            print(f"  [{idx}] 偏移 {offset}: 剩余 {len(raw) - offset} 字节不足解析（需 >=3）")
            break

        tag = struct.unpack_from(fmt_type, raw, offset)[0]
        length = struct.unpack_from(fmt_len, raw, offset + 1)[0]
        value_start = offset + 3
        value_end = value_start + length

        if value_end > len(raw):
            print(f"  [{idx}] Tag=0x{tag:02X}, Length={length} — 数据截断（实际只剩 {len(raw) - value_start} 字节）")
            break

        value = raw[value_start:value_end]
        print(f"  [{idx}] Tag=0x{tag:02X}, Length={length}, Value={value.hex().upper()}")
        offset = value_end
        idx += 1

    print(f"\n共解析 {idx - 1} 个 TLV 字段")


def parse_custom(raw: bytes, spec_json: str, endian: str) -> None:
    try:
        spec = json.loads(spec_json)
    except json.JSONDecodeError as e:
        print(f"错误：custom_spec JSON 解析失败 — {e}")
        return

    print("=== 自定义帧解析 ===")
    print(f"总长度       : {len(raw)} 字节")
    print()

    offset = 0
    parsed_fields: dict = {}

    for field in spec:
        name = field["name"]
        nbytes = field["bytes"]
        field_endian = field.get("endian", endian)
        field_type = field.get("type", "raw")

        # bytes 可以是整数或引用前面已解析字段的名称
        if isinstance(nbytes, str):
            nbytes = parsed_fields.get(nbytes, 0)

        if offset + nbytes > len(raw):
            print(f"  {name:12s} : 数据不足（需 {nbytes} 字节，剩余 {len(raw) - offset}）")
            break

        chunk = raw[offset:offset + nbytes]

        if field_type == "crc16":
            payload_for_crc = raw[:offset]
            computed = crc16_ccitt(payload_for_crc)
            received = int.from_bytes(chunk, byteorder=field_endian)
            status = "通过" if computed == received else f"失败（期望 0x{computed:04X}）"
            print(f"  {name:12s} : 0x{received:04X} — CRC16 校验{status}")
        elif nbytes <= 8:
            val = int.from_bytes(chunk, byteorder=field_endian)
            parsed_fields[name] = val
            print(f"  {name:12s} : 0x{val:0{nbytes*2}X} ({val})")
        else:
            print(f"  {name:12s} : {chunk.hex().upper()} ({nbytes} 字节)")

        offset += nbytes


def auto_detect(raw: bytes, endian: str) -> None:
    # 简单启发式：如果长度 >= 14 且 bytes 12-13 是常见 EtherType → Ethernet
    if len(raw) >= 14:
        etype = struct.unpack("!H", raw[12:14])[0]
        if etype in (0x0800, 0x0806, 0x86DD, 0x8100):
            parse_ethernet(raw)
            return

    # 否则尝试 TLV
    parse_tlv(raw, endian)


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

    hex_data = payload.get("hex_data", "").strip().replace(" ", "").replace("0x", "").replace("0X", "")
    fmt = payload.get("format", "auto")
    endian = payload.get("endian", "big")
    custom_spec = payload.get("custom_spec", "")

    if len(hex_data) % 2 != 0:
        print("错误：hex_data 长度为奇数，非法十六进制串。")
        return

    try:
        raw = bytes.fromhex(hex_data)
    except ValueError as e:
        print(f"错误：hex_data 包含非法字符 — {e}")
        return

    if len(raw) == 0:
        print("错误：输入帧数据为空。")
        return

    if fmt == "ethernet":
        parse_ethernet(raw)
    elif fmt == "tlv":
        parse_tlv(raw, endian)
    elif fmt == "custom":
        if not custom_spec:
            print("错误：format=custom 但未提供 custom_spec。")
            return
        parse_custom(raw, custom_spec, endian)
    else:
        auto_detect(raw, endian)


if __name__ == "__main__":
    main()

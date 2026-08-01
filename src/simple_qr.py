"""Minimal QR Code Model 2 encoder for short connection URLs.

This encodes byte-mode payloads as a Version 3-L symbol. That version holds up
to 53 UTF-8 bytes, which comfortably covers an IPv4 HTTP URL with a port.
"""


QR_VERSION = 3
QR_SIZE = 29
DATA_CODEWORDS = 55
ERROR_CODEWORDS = 15


def _append_bits(bits, value, length):
    bits.extend((value >> shift) & 1 for shift in range(length - 1, -1, -1))


def _gf_multiply(left, right):
    result = 0
    for bit in range(7, -1, -1):
        result = (result << 1) ^ ((result >> 7) * 0x11D)
        result ^= ((right >> bit) & 1) * left
    return result


def _reed_solomon_divisor(degree):
    result = [0] * degree
    result[-1] = 1
    root = 1
    for _ in range(degree):
        for index in range(degree):
            result[index] = _gf_multiply(result[index], root)
            if index + 1 < degree:
                result[index] ^= result[index + 1]
        root = _gf_multiply(root, 2)
    return result


def _reed_solomon_remainder(data, divisor):
    result = [0] * len(divisor)
    for value in data:
        factor = value ^ result[0]
        result = result[1:] + [0]
        for index, coefficient in enumerate(divisor):
            result[index] ^= _gf_multiply(coefficient, factor)
    return result


def _encode_codewords(text):
    payload = text.encode("utf-8")
    if len(payload) > 53:
        raise ValueError("QR payload exceeds the Version 3-L byte capacity")

    bits = []
    _append_bits(bits, 0b0100, 4)
    _append_bits(bits, len(payload), 8)
    for value in payload:
        _append_bits(bits, value, 8)

    capacity = DATA_CODEWORDS * 8
    bits.extend([0] * min(4, capacity - len(bits)))
    bits.extend([0] * ((-len(bits)) % 8))
    data = [
        sum(bits[offset + bit] << (7 - bit) for bit in range(8))
        for offset in range(0, len(bits), 8)
    ]
    pads = (0xEC, 0x11)
    pad_index = 0
    while len(data) < DATA_CODEWORDS:
        data.append(pads[pad_index % 2])
        pad_index += 1

    divisor = _reed_solomon_divisor(ERROR_CODEWORDS)
    return data + _reed_solomon_remainder(data, divisor)


def _format_bits(mask):
    data = (0b01 << 3) | mask  # Error correction level L.
    remainder = data << 10
    while remainder.bit_length() >= 11:
        remainder ^= 0x537 << (remainder.bit_length() - 11)
    return ((data << 10) | remainder) ^ 0x5412


def qr_matrix(text):
    """Return the symbol as a list of rows containing boolean modules."""
    codewords = _encode_codewords(text)
    modules = [[False] * QR_SIZE for _ in range(QR_SIZE)]
    functions = [[False] * QR_SIZE for _ in range(QR_SIZE)]

    def set_function(x, y, dark):
        modules[y][x] = dark
        functions[y][x] = True

    def draw_finder(center_x, center_y):
        for delta_y in range(-4, 5):
            for delta_x in range(-4, 5):
                x = center_x + delta_x
                y = center_y + delta_y
                if 0 <= x < QR_SIZE and 0 <= y < QR_SIZE:
                    distance = max(abs(delta_x), abs(delta_y))
                    set_function(x, y, distance not in (2, 4))

    def draw_alignment(center_x, center_y):
        for delta_y in range(-2, 3):
            for delta_x in range(-2, 3):
                distance = max(abs(delta_x), abs(delta_y))
                set_function(
                    center_x + delta_x,
                    center_y + delta_y,
                    distance != 1,
                )

    def draw_format(mask):
        bits = _format_bits(mask)
        for index in range(6):
            set_function(8, index, ((bits >> index) & 1) != 0)
        set_function(8, 7, ((bits >> 6) & 1) != 0)
        set_function(8, 8, ((bits >> 7) & 1) != 0)
        set_function(7, 8, ((bits >> 8) & 1) != 0)
        for index in range(9, 15):
            set_function(14 - index, 8, ((bits >> index) & 1) != 0)
        for index in range(8):
            set_function(QR_SIZE - 1 - index, 8, ((bits >> index) & 1) != 0)
        for index in range(8, 15):
            set_function(8, QR_SIZE - 15 + index, ((bits >> index) & 1) != 0)
        set_function(8, QR_SIZE - 8, True)

    draw_finder(3, 3)
    draw_finder(QR_SIZE - 4, 3)
    draw_finder(3, QR_SIZE - 4)
    for index in range(8, QR_SIZE - 8):
        set_function(6, index, index % 2 == 0)
        set_function(index, 6, index % 2 == 0)
    draw_alignment(22, 22)
    draw_format(0)

    bit_index = 0
    right = QR_SIZE - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vertical in range(QR_SIZE):
            y = QR_SIZE - 1 - vertical if upward else vertical
            for offset in range(2):
                x = right - offset
                if not functions[y][x]:
                    bit = False
                    if bit_index < len(codewords) * 8:
                        bit = ((codewords[bit_index >> 3] >> (7 - (bit_index & 7))) & 1) != 0
                    modules[y][x] = bit ^ ((x + y) % 2 == 0)  # Mask pattern 0.
                    bit_index += 1
        right -= 2

    return modules


def qr_svg(text, scale=6, border=4):
    """Render a QR symbol as an inline SVG string."""
    matrix = qr_matrix(text)
    view_size = QR_SIZE + border * 2
    path = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                path.append("M%s %sh1v1h-1z" % (x + border, y + border))
    return (
        '<svg class="qr-code" xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 {view} {view}" width="{width}" height="{width}" '
        'role="img" aria-label="QR code for connection URL" shape-rendering="crispEdges">'
        '<rect width="100%" height="100%" fill="#fff"/>'
        '<path d="{path}" fill="#000"/></svg>'
    ).format(view=view_size, width=view_size * scale, path=''.join(path))

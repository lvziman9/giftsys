import base64
import hashlib
import random
import string


def generate_claim_code() -> str:
    chars = string.ascii_uppercase + string.digits
    body = "".join(random.choice(chars) for _ in range(6))
    return f"GF-{body}"


def demo_qr_svg_data_uri(value: str, size: int = 168) -> str:
    grid = 21
    cell = size // grid
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    bits = "".join(f"{byte:08b}" for byte in digest)

    rects = [
        f'<rect width="{size}" height="{size}" fill="white"/>',
    ]

    def add_finder(x: int, y: int) -> None:
        rects.append(f'<rect x="{x * cell}" y="{y * cell}" width="{7 * cell}" height="{7 * cell}" fill="black"/>')
        rects.append(f'<rect x="{(x + 1) * cell}" y="{(y + 1) * cell}" width="{5 * cell}" height="{5 * cell}" fill="white"/>')
        rects.append(f'<rect x="{(x + 2) * cell}" y="{(y + 2) * cell}" width="{3 * cell}" height="{3 * cell}" fill="black"/>')

    add_finder(1, 1)
    add_finder(13, 1)
    add_finder(1, 13)

    bit_index = 0
    for row in range(grid):
        for col in range(grid):
            in_finder = (
                (1 <= col <= 7 and 1 <= row <= 7)
                or (13 <= col <= 19 and 1 <= row <= 7)
                or (1 <= col <= 7 and 13 <= row <= 19)
            )
            if in_finder:
                continue
            if bits[bit_index % len(bits)] == "1":
                rects.append(
                    f'<rect x="{col * cell}" y="{row * cell}" width="{cell}" height="{cell}" fill="black"/>'
                )
            bit_index += 1

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" role="img" aria-label="Demo QR code">'
        + "".join(rects)
        + "</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


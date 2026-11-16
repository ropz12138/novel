"""Test double for the length-prefixed XTTS worker protocol."""
import struct
import sys


def main() -> None:
    while True:
        header = sys.stdin.buffer.read(4)
        if len(header) < 4:
            return
        size = struct.unpack("<I", header)[0]
        if size == 0:
            return
        text = sys.stdin.buffer.read(size)
        if text == "失败".encode():
            message = "合成失败".encode()
            sys.stdout.buffer.write(struct.pack("<II", 0xFFFFFFFF, len(message)) + message)
        else:
            pcm = b"PCM:" + text
            sys.stdout.buffer.write(struct.pack("<I", len(pcm)) + pcm)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

from typing import Union


WritableMemory = Union[memoryview, bytearray]
ReadableMemory = Union[memoryview, bytes, bytearray]
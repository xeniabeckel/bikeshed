from __future__ import annotations
import collections
import dataclasses
from dataclasses import dataclass
import typing
from typing import Union, Optional, Dict, NamedTuple, Any

###################
# Support classes #
###################

@dataclass
class Stream:
    _chars: str
    errors: list["ParseError"] = []
    #config: parsing.ParseConfig

    def __getitem__(self, key: Union[int, slice]) -> str:
        try:
            return self._chars[key]
        except IndexError:
            return ""

    def eof(self, index: int) -> bool:
        return index >= len(self._chars)


class Failure:
    pass


class Result(NamedTuple):
    value: Any
    end: int

    @property
    def valid(self) -> bool:
        return self.value is not Failure

    @staticmethod
    def fail(index: int) -> Result:
        return Result(Failure, index)


class ParseError(Exception):
    def __init__(self, s: Union[str, stream.Stream], i: int, msg: str):
        self.line, self.col = lineCol(s, i)
        self.msg = f"{self.line}:{self.col} parse error:"
        if "\n" in msg:
            self.msg += "\n" + msg
        elif len(self.msg) + len(msg) + 1 > 78:
            self.msg += "\n  " + msg
        else:
            self.msg += " " + msg
        super().__init__(self.msg)


def lineCol(s: Union[str, stream.Stream], index: int) -> Tuple[int, int]:
    """Determines the line and column from an index."""
    line = 1
    col = 1
    for i in range(index):
        if s[i] == "\n":
            line += 1
            col = 1
            continue
        col += 1
    return line, col


##########
# Parser #
##########

Node = Union[str, "Element"]

@dataclass
class Element:
    tag: str
    attrs: Dict[str, str] = {}
    nodes: list[Node] = []


def parseElement(s: Stream, start: int) -> Result:
    i = start
    if s[i] != "<":
        return Result.fail(start)
    i += 1

    tag, i = parseTagName(s, i)
    if tag is Failure:
        return Result.fail(start)
    if s.eof(i):
        s.errors.append(f"Hit EOF in an unclosed tag {s[start: i]}.")
        return Result.fail(i)


def parseTagName(s: Stream, start: int) -> Result:
    i = start

    tag = ""
    if not s[i].isalpha():
        return Result.fail(start)
    tag += s[i]
    i += 1

    while isTagNameChar(s[i]):
        if s[i] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            tag += s[i].lower()
        elif ord(s[i]) == 0:
            s.errors.append(f"Null byte in tag name at {':'.join(lineCol(s, i))}.")
            tag += chr(0xfffd)
        else:
            tag += s[i]
        i += 1
    return Result(tag, i)


def isTagNameChar(ch: str) -> bool:
    if ch == "":
        return False
    cp = ord(ch)
    if ord in (0x9, 0xa, 0xc, 0x20, 0x2f, 0x3e):
        return False
    return True
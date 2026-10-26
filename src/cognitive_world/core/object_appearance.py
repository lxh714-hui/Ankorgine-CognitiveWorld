"""Closed authored visual evidence, never a general attributes disclosure rule."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ObjectAppearance:
    version: int
    shape: str
    detail: str
    visible: bool
    detail_visible: bool

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported object appearance version")
        if self.shape not in {"small", "box", "flat"} or self.detail not in {"notched", "striped", "plain"}:
            raise ValueError("unsupported authored visual feature")
        if type(self.visible) is not bool or type(self.detail_visible) is not bool:
            raise TypeError("appearance permissions must be booleans")

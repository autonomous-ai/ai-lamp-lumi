from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import cv2


type SendEventCallable = Callable[
    [str, str, cv2.typing.MatLike, list[cv2.typing.MatLike], float | None], None
]

type OnMotionCallable = Callable[[], None]

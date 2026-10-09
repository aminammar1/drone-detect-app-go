"""Preview-window cancellation should respond to keys and title-bar close."""

from detector import main


def test_preview_quits_on_q(monkeypatch) -> None:
    monkeypatch.setattr(main.cv2, "waitKey", lambda _: ord("q"))
    assert main._preview_stop_requested()


def test_preview_quits_on_escape(monkeypatch) -> None:
    monkeypatch.setattr(main.cv2, "waitKey", lambda _: 27)
    assert main._preview_stop_requested()


def test_preview_quits_when_window_is_closed(monkeypatch) -> None:
    monkeypatch.setattr(main.cv2, "waitKey", lambda _: -1)
    monkeypatch.setattr(main.cv2, "getWindowProperty", lambda *_: 0)
    assert main._preview_stop_requested()


def test_preview_stays_open_when_visibility_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(main.cv2, "waitKey", lambda _: -1)

    def unavailable(*_):
        raise main.cv2.error("visibility unavailable")

    monkeypatch.setattr(main.cv2, "getWindowProperty", unavailable)
    assert not main._preview_stop_requested()

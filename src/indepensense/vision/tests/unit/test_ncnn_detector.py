"""The NCNN detector's geometry, decoding and NMS — the parts ultralytics used to do.

Pure numpy; `ncnn` is not needed and not imported. Agreement with
ultralytics on real images was checked separately (175 of 182 boxes matched
at IoU > 0.9 on the Commons street set; the rest sit on the threshold,
where NCNN's bilinear resize differs slightly from OpenCV's).
"""
import numpy as np
import pytest

from indepensense.vision.ncnn_detector import decode, letterbox_geometry, nms, read_metadata


def test_letterbox_fits_camera_frame_into_square():
    scale, w, h, left, top = letterbox_geometry(1280, 720, 640)
    assert scale == 0.5
    assert (w, h) == (640, 360)
    assert (left, top) == (0, 140)


def test_letterbox_splits_odd_padding_like_ultralytics():
    """Ultralytics rounds (pad/2 - 0.1) for the top, the rest goes to the bottom."""
    _, _, h, _, top = letterbox_geometry(640, 481, 640)
    assert h == 481
    assert top == 79 and 640 - h - top == 80


def _head(boxes_cxcywh, class_scores):
    """Build a raw (4 + C, N) head from per-candidate boxes and score rows."""
    return np.concatenate([np.array(boxes_cxcywh, dtype=np.float32).T,
                           np.array(class_scores, dtype=np.float32).T])


def test_decode_maps_back_to_source_pixels():
    # A 100x50 box centred at (320, 320) in the 640 input of a 1280x720 frame.
    out = _head([[320, 320, 100, 50]], [[0.1, 0.9]])
    boxes, scores, ids = decode(out, 0.3, 0.5, 0, 140, 1280, 720)
    assert ids.tolist() == [1]
    assert scores[0] == pytest.approx(0.9)
    np.testing.assert_allclose(boxes[0], [540, 310, 740, 410])


def test_decode_drops_candidates_below_threshold():
    out = _head([[100, 100, 10, 10], [200, 200, 10, 10]], [[0.2, 0.1], [0.05, 0.35]])
    _, scores, ids = decode(out, 0.3, 1.0, 0, 0, 640, 640)
    assert ids.tolist() == [1] and scores.tolist() == pytest.approx([0.35])


def test_decode_clips_to_frame():
    out = _head([[5, 5, 40, 40]], [[0.9]])
    boxes, _, _ = decode(out, 0.3, 1.0, 0, 0, 640, 640)
    assert boxes[0].tolist() == [0, 0, 25, 25]


def test_nms_suppresses_overlapping_same_class():
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105], [300, 300, 400, 400]], dtype=np.float32)
    keep = nms(boxes, np.array([0.9, 0.8, 0.7]), np.array([0, 0, 0]))
    assert keep == [0, 2]


def test_nms_never_suppresses_across_classes():
    """A person standing in front of a jeepney is two objects, not one."""
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105]], dtype=np.float32)
    assert nms(boxes, np.array([0.9, 0.8]), np.array([0, 1])) == [0, 1]


def test_nms_of_nothing():
    assert nms(np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int)) == []


def test_metadata_gives_names_in_index_order(tmp_path):
    (tmp_path / "metadata.yaml").write_text("imgsz:\n- 640\n- 640\nnames:\n  1: tricycle\n  0: jeepney\n")
    assert read_metadata(tmp_path) == (["jeepney", "tricycle"], 640)

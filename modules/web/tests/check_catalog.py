"""
File: Cully/modules/web/tests/check_catalog.py
Description: Checks the catalog additions the web app needs: WAL mode, culled status and the faces of a
photo. Uses a throwaway catalog in a temp folder, never the real one.

Run from Cully/modules with either venv:
    python -m web.tests.check_catalog
Author: Miguel Macias
Date: 2026-11-16
"""

from pathlib import Path
import tempfile

import cv2
import numpy as np

from models.catalog import Catalog
from models.photo import Photo


def make_catalog(folder: Path) -> tuple[Catalog, Photo]:
    """A catalog holding one plain JPG with one person box and one face box."""
    image = folder / "photo.jpg"
    cv2.imwrite(str(image), np.full((60, 80, 3), 128, np.uint8))
    photo = Photo(image)
    catalog = Catalog(str(folder / "catalog.db"))
    catalog.insert_photo(photo)
    assert catalog.cursor is not None and catalog.catalog_connection is not None
    cursor = catalog.cursor
    cursor.execute(
        "INSERT INTO bounding_boxes (id, image_hash, confidence, name, x1, y1, x2, y2) "
        "VALUES (1, ?, 0.9, 'person', 0, 0, 80, 60)",
        (photo.image_hash,),
    )
    cursor.execute(
        "INSERT INTO face_boxes (id, name, parent_box_id, confidence, x1, y1, x2, y2) "
        "VALUES (7, 'Face Box', 1, 0.8, 10, 10, 30, 30)"
    )
    # Detector marker rows are not faces and must not show up
    cursor.execute(
        "INSERT INTO face_boxes (id, name, parent_box_id, confidence, x1, y1, x2, y2) "
        "VALUES (8, 'No Faces Found', 1, 0, 0, 0, 80, 60)"
    )
    cursor.execute("INSERT INTO face_scores VALUES (7, 'laplacian', 123.5)")
    cursor.execute(
        "INSERT INTO face_landmarks (face_box_id, image_hash, ear_left, ear_right) VALUES (7, ?, 0.3, 0.28)",
        (photo.image_hash,),
    )
    catalog.catalog_connection.commit()
    return catalog, photo


def test_wal_mode():
    with tempfile.TemporaryDirectory() as folder:
        catalog, _ = make_catalog(Path(folder))
        assert catalog.cursor is not None
        mode = catalog.cursor.execute("PRAGMA journal_mode").fetchone()[0]
        catalog.close()
        assert mode == "wal", mode


def test_set_culled_status():
    with tempfile.TemporaryDirectory() as folder:
        catalog, photo = make_catalog(Path(folder))
        assert catalog.set_culled_status(photo.image_hash, "keep") is True
        assert catalog.set_culled_status("0" * 64, "keep") is False
        try:
            catalog.set_culled_status(photo.image_hash, "maybe")
            raise AssertionError("a bad status should raise")
        except ValueError:
            pass
        statuses = [p.culled_status for p in catalog.get_report_photos()]
        catalog.close()
        assert statuses == ["keep"], statuses


def test_clear_status():
    with tempfile.TemporaryDirectory() as folder:
        catalog, photo = make_catalog(Path(folder))
        catalog.set_culled_status(photo.image_hash, "reject")
        assert catalog.set_culled_status(photo.image_hash, None) is True
        statuses = [p.culled_status for p in catalog.get_report_photos()]
        catalog.close()
        assert statuses == [None], statuses


def test_status_survives_ranking_and_rescan():
    with tempfile.TemporaryDirectory() as folder:
        catalog, photo = make_catalog(Path(folder))
        catalog.set_culled_status(photo.image_hash, "keep")
        catalog.clear_burst_ranking()
        catalog.insert_photo(photo)  # what a rescan of the folder does
        statuses = [p.culled_status for p in catalog.get_report_photos()]
        catalog.close()
        assert statuses == ["keep"], statuses


def test_faces_for_photo():
    with tempfile.TemporaryDirectory() as folder:
        catalog, photo = make_catalog(Path(folder))
        faces = catalog.get_faces_for_photo(photo.image_hash, "laplacian")
        above = catalog.get_faces_for_photo(
            photo.image_hash, "laplacian", min_confidence=0.95
        )
        other_method = catalog.get_faces_for_photo(photo.image_hash, "tenengrad")
        catalog.close()
        assert [f.face_box_id for f in faces] == [7], faces
        assert (faces[0].sharpness, faces[0].ear_left, faces[0].ear_right) == (
            123.5,
            0.3,
            0.28,
        )
        assert above == []
        # No score for that method yet, the face is still listed
        assert other_method[0].sharpness is None


def make_burst_catalog(folder: Path) -> tuple[Catalog, int, int, list[str]]:
    """Returns back a catalog with 1 event, 1 burst and 3 ranked photos (only the first is a candidate),
    plus the burst id, the event id and the 3 hashes in rank order"""
    catalog = Catalog(str(folder / "catalog.db"))
    assert catalog.cursor is not None and catalog.catalog_connection is not None
    cursor = catalog.cursor

    #Different fills so each image gets its own hash
    hashes = []
    for i, fill in enumerate((50, 100, 150)):
        image = folder / f"burst_{i}.jpg"
        cv2.imwrite(str(image), np.full((60, 80, 3), fill, np.uint8))
        photo = Photo(image)
        catalog.insert_photo(photo)
        hashes.append(photo.image_hash)

    #Event first, then the burst inside it
    start, end = "2026-01-01T10:00:00.000", "2026-01-01T10:00:02.000"
    insert_group = (
        "INSERT INTO photo_groups (kind, parent_id, camera_model, start_time, end_time) "
        "VALUES (?, ?, NULL, ?, ?)"
    )
    cursor.execute(insert_group, ("event", None, start, end))
    event_id = cursor.lastrowid
    cursor.execute(insert_group, ("burst", event_id, start, end))
    burst_id = cursor.lastrowid
    assert event_id is not None and burst_id is not None

    #Rank 1 is the only candidate
    for position, image_hash in enumerate(hashes):
        cursor.execute(
            "INSERT INTO photo_group_members (group_id, image_hash, position) VALUES (?, ?, ?)",
            (burst_id, image_hash, position),
        )
        cursor.execute(
            "UPDATE photos SET burst_rank = ?, is_candidate = ? WHERE image_hash = ?",
            (position + 1, 1 if position == 0 else 0, image_hash),
        )
    catalog.catalog_connection.commit()
    return catalog, burst_id, event_id, hashes


def test_accept_burst():
    with tempfile.TemporaryDirectory() as folder:
        catalog, burst_id, event_id, hashes = make_burst_catalog(Path(folder))
        result = catalog.accept_burst(burst_id)
        status = {p.image_hash: p.culled_status for p in catalog.get_report_photos()}
        catalog.close()
        assert result == (1,2), result
        assert [status[h] for h in hashes] == ['keep','reject','reject'], status


def test_accept_burst_skips_marked():
    with tempfile.TemporaryDirectory() as folder:
        catalog, burst_id, _, hashes = make_burst_catalog(Path(folder))

        #hashes[1] is not a candidate, the ranking would reject it, so keep it by hand
        catalog.set_culled_status(hashes[1], "keep")
        result = catalog.accept_burst(burst_id)
        statuses = {p.image_hash: p.culled_status for p in catalog.get_report_photos()}
        catalog.close()

        #Only hashes[0] (keep) and hashes[2] (reject) were changed by accept
        assert result == (1, 1), result
        assert statuses[hashes[1]] == "keep", statuses
        assert statuses[hashes[0]] == "keep" and statuses[hashes[2]] == "reject", statuses

def test_accept_unknown_burst():
    with tempfile.TemporaryDirectory() as folder:
        catalog, burst_id, event_id, hashes = make_burst_catalog(Path(folder))
        unknown_burst_99999 = catalog.accept_burst(99999)
        unknown_burst_event_id = catalog.accept_burst(event_id)
        catalog.close()
        assert unknown_burst_99999 is None
        assert unknown_burst_event_id is None



if __name__ == "__main__":
    tests = [
        value for name, value in dict(globals()).items() if name.startswith("test_")
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as e:  # a missing method shows as a failure, not a crash
            failed += 1
            print(f"  [FAIL] {test.__name__} {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)

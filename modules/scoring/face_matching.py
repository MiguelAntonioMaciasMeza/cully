"""
File: Cully/modules/scoring/face_matching.py
Description: Works out which faces in a burst belong to the same person by where their boxes are.
Burst frames are seconds apart with the same framing, so a person's face box barely moves between
frames. Each person keeps their last seen box, so a face missing for a frame can still rejoin.
Embeddings aren't used here, they're kept for looking up a subject across the catalog.
Author: Miguel Macias
Date: 2026-11-15
"""

from collections import defaultdict

from models.face_score import FaceScore

MIN_IOU = 0.3

Box = tuple[int, int, int, int]


def iou(a: Box, b: Box) -> float:
    """Overlap of two (x1, y1, x2, y2) boxes: 1.0 = same box, 0.0 = not touching."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    overlap = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap)


def match_by_position(faces: list[FaceScore], frame_order: list[str], min_iou: float = MIN_IOU):
    """Sets person_id on each face. frame_order is the burst's image hashes in capture order."""
    by_frame: defaultdict[str, list[FaceScore]] = defaultdict(list)
    for face in faces:
        by_frame[face.image_hash].append(face)

    last_box: dict[int, Box] = {}  # person id -> where we last saw them
    for image_hash in frame_order:
        frame = [face for face in by_frame[image_hash] if face.box is not None]
        # Best overlaps get paired first, each face and person used once
        pairs = sorted(
            ((iou(face.box, box), index, person) for index, face in enumerate(frame)
             for person, box in last_box.items()),
            reverse=True,
        )
        matched_faces: set[int] = set()
        matched_people: set[int] = set()
        for overlap, index, person in pairs:
            if overlap < min_iou:
                break
            if index in matched_faces or person in matched_people:
                continue
            frame[index].person_id = person
            matched_faces.add(index)
            matched_people.add(person)

        # Anyone left over is new to the burst
        for index, face in enumerate(frame):
            if index not in matched_faces:
                face.person_id = len(last_box) + 1
            last_box[face.person_id] = face.box

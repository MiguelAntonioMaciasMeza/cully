"""
File: Cully/modules/scoring/burst_rank.py
Description: Ranks the photos of one burst against each other. Raw sharpness and EAR don't
compare across scenes or people so everything is ranked relative to each other.
As of now the rankings across bursts only use two metrics: 
    -Eyes: an eye is closed below its EAR threshold
    -Sharpness: a photo scores as its weakest face, so one soft face drags a group shot down.
Photos with no faces aren't in the input, so they're left unranked, thinking how to address in the future.
Author: Miguel Macias
Date: 2026-11-06
"""

from collections import defaultdict

from models.face_score import FaceScore, RankedPhoto

EYE_GATE = 0.6
# Open eyes measure about 0.25-0.35, closed under about 0.13. Below this an eye is closed no matter
# what the rest of the burst looks like, which covers faces seen in only one frame
EAR_FLOOR = 0.15


def _ratio(value: float, best: float) -> float:
    # A best of 0 means every frame is equally bad, so nobody is worse than the best
    return value / best if best > 0 else 1.0


def rank_burst(
    faces: list[FaceScore], eye_gate: float = EYE_GATE, ear_floor: float = EAR_FLOOR
) -> list[RankedPhoto]:
    # Faces without a person id can't be matched across frames, so each is its own person
    by_person: defaultdict[object, list[FaceScore]] = defaultdict(list)
    for face in faces:
        key = face.person_id if face.person_id is not None else ("face", face.face_box_id)
        by_person[key].append(face)

    # Each face's sharpness ratio and open/closed, collected per photo
    sharp_by_photo: defaultdict[str, list[float]] = defaultdict(list)
    open_by_photo: defaultdict[str, list[bool]] = defaultdict(list)
    for person_faces in by_person.values():
        best_sharp = max(face.sharpness for face in person_faces)
        ears = [face.ear for face in person_faces if face.ear is not None]
        best_ear = max(ears) if ears else 0.0
        for face in person_faces:
            sharp_by_photo[face.image_hash].append(_ratio(face.sharpness, best_sharp))
            # No EAR means we can't tell, so don't punish the photo for it
            eyes_open = face.ear is None or (
                face.ear >= ear_floor and _ratio(face.ear, best_ear) >= eye_gate
            )
            open_by_photo[face.image_hash].append(eyes_open)

    ranked = [
        RankedPhoto(image_hash, min(ratios), all(open_by_photo[image_hash]))
        for image_hash, ratios in sharp_by_photo.items()
    ]
    ranked.sort(key=lambda photo: (photo.eyes_open, photo.score), reverse=True)
    for rank, photo in enumerate(ranked, 1):
        photo.rank = rank
    return ranked

"""
File: Cully/modules/scoring/burst_rank.py
Description: Ranks the photos of one burst against each other. Raw sharpness and EAR don't
compare across scenes or people so everything is ranked relative to each other.
Photos with faces are ranked on:
    -Eyes: an eye is closed below its EAR threshold. eye_check=False skips this, sharpness only
    -Sharpness: a photo scores as its weakest face, so one soft face drags a group shot down.
    -Exposure: a photo with an exposure problem (scoring/exposure.py) is penalised like closed eyes.
Photos with no usable face are ranked on whole-frame sharpness instead (rank_frames). In a burst with
faces they come after the face photos and are never candidates, the two scores don't compare.
Candidates: rank 1 unless it has an exposure problem, plus good photos (open eyes, fine exposure)
scoring at least candidate_margin of the best.
Author: Miguel Macias
Date: 2026-11-06
"""

from collections import defaultdict

from models.face_score import FaceScore, RankedPhoto

EYE_GATE = 0.6
# Open eyes measure about 0.25-0.35, closed under about 0.13. Below this an eye is closed no matter
# what the rest of the burst looks like, which covers faces seen in only one frame
EAR_FLOOR = 0.15
# Photos at or above this share of the best score (with open eyes) are candidates
CANDIDATE_MARGIN = 0.9


def _ratio(value: float, best: float) -> float:
    # A best of 0 means every frame is equally bad, so nobody is worse than the best
    return value / best if best > 0 else 1.0


def rank_burst(
    faces: list[FaceScore],
    eye_gate: float = EYE_GATE,
    ear_floor: float = EAR_FLOOR,
    eye_check: bool = True,
    candidate_margin: float = CANDIDATE_MARGIN,
    max_candidates: int = 0,
    exposure: dict[str, str | None] | None = None,
) -> list[RankedPhoto]:
    """Ranks the photos that have faces. exposure maps a photo to its exposure problem, if any."""
    exposure = exposure or {}
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
            eyes_open = not eye_check or face.ear is None or (
                face.ear >= ear_floor and _ratio(face.ear, best_ear) >= eye_gate
            )
            open_by_photo[face.image_hash].append(eyes_open)

    ranked = [
        RankedPhoto(image_hash, min(ratios), all(open_by_photo[image_hash]), exposure_issue=exposure.get(image_hash))
        for image_hash, ratios in sharp_by_photo.items()
    ]
    return _order_and_pick(ranked, candidate_margin, max_candidates)


def rank_frames(
    sharpness: dict[str, float],
    exposure: dict[str, str | None] | None = None,
    candidate_margin: float = CANDIDATE_MARGIN,
    max_candidates: int = 0,
) -> list[RankedPhoto]:
    """Ranks photos with no usable face on whole-frame sharpness, relative to the sharpest."""
    exposure = exposure or {}
    best = max(sharpness.values(), default=0.0)
    ranked = [
        RankedPhoto(image_hash, _ratio(value, best), None, exposure_issue=exposure.get(image_hash))
        for image_hash, value in sharpness.items()
    ]
    return _order_and_pick(ranked, candidate_margin, max_candidates)


def append_ranked(first: list[RankedPhoto], after: list[RankedPhoto]) -> list[RankedPhoto]:
    """Puts after's photos below first's, renumbered and never candidates (their scores don't compare)."""
    for offset, photo in enumerate(after, len(first) + 1):
        photo.rank = offset
        photo.is_candidate = False
    return first + after


def _order_and_pick(ranked: list[RankedPhoto], candidate_margin: float, max_candidates: int) -> list[RankedPhoto]:
    """Sorts good photos first then by score, numbers them and marks the candidates."""
    ranked.sort(key=lambda photo: (photo.is_good, photo.score), reverse=True)
    for rank, photo in enumerate(ranked, 1):
        photo.rank = rank

    # Rank 1 stays unless its exposure failed; others need to be good and score near the best
    count = 0
    for photo in ranked:
        first = photo.rank == 1 and photo.exposure_issue is None
        close = photo.is_good and photo.score >= candidate_margin
        if first or (close and (max_candidates == 0 or count < max_candidates)):
            photo.is_candidate = True
            count += 1
    return ranked

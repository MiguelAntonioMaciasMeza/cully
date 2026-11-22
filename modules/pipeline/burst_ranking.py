"""
File: Cully/modules/pipeline/burst_ranking.py
Description: Regroups the catalog into bursts, ranks the photos in each burst by face sharpness
and eye openness (see scoring/burst_rank.py). This is ran after the initial pipeline of determining
eye state and sharpness calculation
Faces are matched across frames by box position (scoring/face_matching.py), not embeddings, and
faces below the face_threshold setting are left out. Burst/event gaps come from the grouping
setting, eye and matching values from the ranking setting (eye_check off ranks on sharpness only).
Exposure problems (scoring/exposure.py, exposure setting) are found per burst and penalise a photo
like closed eyes. Photos with no usable face are ranked on whole-frame sharpness from the exposure step.
Each photo's score, rank, eyes open, candidate and exposure flags are saved to the photos table.
Run with venv-faces, pipeline/grouping.py imports scipy and deepface.
Author: Miguel Macias
Date: 2026-11-06
"""

from dataclasses import dataclass, field
from datetime import timedelta

from config.settings import Settings
from utils.steps import fingerprint
from models.catalog import Catalog
from models.face_score import RankedPhoto
from pipeline.grouping import ImageGrouper
from scoring.burst_rank import append_ranked, rank_burst, rank_frames
from scoring.exposure import exposure_issues
from scoring.face_matching import match_by_position


@dataclass
class BurstRankStep:
    catalog: Catalog = field(default_factory=Catalog)
    settings: Settings = field(default_factory=Settings)

    def run(self, method: str | None = None) -> list[list[RankedPhoto]]:
        method = method or self.settings.models["sharpness"]
        grouping, ranking = self.settings.grouping, self.settings.ranking
        events = ImageGrouper(self.catalog).group_by_capture_time(
            timedelta(seconds=grouping["burst_gap_seconds"]),
            timedelta(minutes=grouping["event_gap_minutes"]),
        )
        # Rankings are saved through the stored groups, so store these first
        self.catalog.replace_photo_groups(events)
        # Photos that drop out of ranking on a rerun shouldn't keep old ranks
        self.catalog.clear_burst_ranking()

        rankings = []
        for event in events:
            for burst in event.bursts:
                hashes = [photo.image_hash for photo in burst.photos]
                metrics = self.catalog.get_photo_metrics(hashes)
                exposure = exposure_issues(
                    metrics,
                    self.catalog.get_face_brightness(hashes, self.settings.face_threshold),
                    self.settings.exposure,
                )
                faces = self.catalog.get_face_scores_for_hashes(
                    hashes, method, self.settings.face_threshold
                )
                ranked = []
                if faces:
                    match_by_position(faces, hashes, ranking["face_match_iou"])
                    ranked = rank_burst(
                        faces,
                        ranking["eye_gate"],
                        ranking["ear_floor"],
                        bool(ranking["eye_check"]),
                        ranking["candidate_margin"],
                        int(ranking["max_candidates"]),
                        exposure,
                    )
                # Photos with no usable face go on whole-frame sharpness, after the face photos
                with_faces = {photo.image_hash for photo in ranked}
                frames = rank_frames(
                    {h: m.sharpness for h, m in metrics.items() if h not in with_faces},
                    exposure,
                    ranking["candidate_margin"],
                    int(ranking["max_candidates"]),
                )
                ranked = append_ranked(ranked, frames) if ranked else frames
                if not ranked:
                    print(f"[burst_ranking.py] Nothing measured in burst starting {burst.start_time}, skipping")
                    continue
                self.catalog.update_burst_ranking(ranked)
                rankings.append(ranked)
        if method == self.settings.models["sharpness"]:
            self.catalog.record_catalog_run("ranking", fingerprint(self.settings, "ranking"))
        return rankings

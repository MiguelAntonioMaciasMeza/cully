"""
File: Cully/modules/pipeline/burst_ranking.py
Description: Regroups the catalog into bursts, ranks the photos in each burst by face sharpness
and eye openness (see scoring/burst_rank.py). This is ran after the initial pipeline of determining
eye state and sharpness calculation
Faces are matched across frames by box position (scoring/face_matching.py), not embeddings, and
faces below the face_threshold setting are left out.
Run with venv-faces, pipeline/grouping.py imports scipy and deepface.
Author: Miguel Macias
Date: 2026-11-06
"""

from dataclasses import dataclass, field

from config.settings import Settings
from models.catalog import Catalog
from models.face_score import RankedPhoto
from pipeline.grouping import ImageGrouper
from scoring.burst_rank import rank_burst
from scoring.face_matching import match_by_position


@dataclass
class BurstRankStep:
    catalog: Catalog = field(default_factory=Catalog)
    settings: Settings = field(default_factory=Settings)

    def run(self, method: str = "laplacian") -> list[list[RankedPhoto]]:
        events = ImageGrouper(self.catalog).group_by_capture_time()
        # Rankings are saved through the stored groups, so store these first
        self.catalog.replace_photo_groups(events)

        rankings = []
        for event in events:
            for burst in event.bursts:
                hashes = [photo.image_hash for photo in burst.photos]
                faces = self.catalog.get_face_scores_for_hashes(
                    hashes, method, self.settings.face_threshold
                )
                if not faces:
                    print(f"[burst_ranking.py] No scored faces in burst starting {burst.start_time}, skipping")
                    continue
                match_by_position(faces, hashes)

                ranked = rank_burst(faces)
                self.catalog.update_burst_ranking(ranked)
                rankings.append(ranked)
        return rankings

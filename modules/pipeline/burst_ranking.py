"""
File: Cully/modules/pipeline/burst_ranking.py
Description: Regroups the catalog into bursts, ranks the photos in each burst by face sharpness
and eye openness (see scoring/burst_rank.py). This is ran after the initial pipeline of determining 
eye state and sharpness calculation 
Author: Miguel Macias
Date: 2026-11-06
"""

from dataclasses import dataclass, field

from models.catalog import Catalog
from models.face_score import RankedPhoto
from pipeline.grouping import FaceGrouper, ImageGrouper
from scoring.burst_rank import rank_burst


@dataclass
class BurstRankStep:
    catalog: Catalog = field(default_factory=Catalog)

    def run(self, method: str = "laplacian") -> list[list[RankedPhoto]]:
        events = ImageGrouper(self.catalog).group_by_capture_time()
        # Rankings are saved through the stored groups, so store these first
        self.catalog.replace_photo_groups(events)
        people = FaceGrouper(self.catalog).group_faces()

        rankings = []
        for event in events:
            for burst in event.bursts:
                hashes = [photo.image_hash for photo in burst.photos]
                faces = self.catalog.get_face_scores_for_hashes(hashes, method)
                if not faces:
                    print(f"[burst_ranking.py] No scored faces in burst starting {burst.start_time}, skipping")
                    continue
                for face in faces:
                    face.person_id = people.get(face.face_box_id)

                ranked = rank_burst(faces)
                self.catalog.update_burst_ranking(ranked)
                rankings.append(ranked)
        return rankings

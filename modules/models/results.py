"""
File: Cully/modules/models/results.py
Description: Contains the models needed to represent Burst/Event results that our pipeline creates.
Each with their respective property 
Author: Miguel Macias
Date: 2026-11-17
"""
from models.report_photo import ReportPhoto
from dataclasses import dataclass, field

@dataclass
class BurstResult:
    """Represents a singular burst within an event"""
    id: int 
    number: int 
    start: str | None
    photos: list[ReportPhoto] = field(default_factory=list)


    @property
    def candidates(self) -> list[ReportPhoto]:
        """Returns back photos within the candidate threshold within a burst"""
        candidate_photos = [p for p in self.photos if p.is_candidate]
        return candidate_photos

    @property
    def rest(self) -> list[ReportPhoto]:
        """Returns back photos that are ranked but however are not in the candidate threshold within a burst"""
        rest = [p for p in self.photos if p.rank is not None and not p.is_candidate]
        return rest

    @property
    def unranked(self) -> list[ReportPhoto]:
        """Returns back unranked photos of a given burst"""
        unranked = [p for p in self.photos if p.rank is None]
        return unranked


@dataclass
class EventResult:
    id: int
    number: int 
    start: str | None
    end: str | None = None
    camera: str | None = None
    bursts: list[BurstResult] = field(default_factory=list)

    @property
    def photos(self) -> list[ReportPhoto]:
        """Returns back every single photo in the burst as a singular list"""
        photos = list()
        for burst in self.bursts:
            for photo in burst.photos:
                photos.append(photo)
        return photos 

    @property
    def candidate_count(self) -> int:
        """Returns total candidate count of an event"""
        photos = self.photos
        count = 0 
        for photo in photos:
            if photo.is_candidate:
                count = count + 1

        return count

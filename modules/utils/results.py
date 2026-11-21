"""
File: Cully/modules/utils/results.py
Description: Any tool that helps results to make a report will be placed here
Author: Miguel Macias
Date: 2026-11-17
"""
from models.report_photo import ReportPhoto
from models.results import EventResult, BurstResult

def group_results(photos: list[ReportPhoto]) -> tuple[list[EventResult], list[ReportPhoto]]:
    """Groups events with their respective Bursts. Returns everything including photos that are not tied
     to an event at the end of the tuple
     """
    counter = 1
    event_list = list()
    loose = list()
    for photo in photos:
        #If no event id just add it into the loose list
        if photo.event_id is None:
            loose.append(photo)
            continue

        #Append a EventResult into the list if the list doesn't exists or event_id differs
        if not event_list or event_list[-1].id != photo.event_id:
            event_list.append(EventResult(id = photo.event_id , number = len(event_list)+ 1, start = photo.event_start, end = photo.event_end, camera = photo.camera_model))

        if len(event_list[-1].bursts) == 0 or photo.burst_id != event_list[-1].bursts[-1].id:
            event_list[-1].bursts.append(BurstResult(id = photo.burst_id, number= counter, start = photo.burst_start))
            counter += 1
        event_list[-1].bursts[-1].photos.append(photo)
    return event_list, loose

        
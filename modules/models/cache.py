"""
File: Cully/modules/models/cache.py
Description: Contains the Cache class which will have a set of image properties such as hashes to later
determine if a file has already been processed or not
Author: Miguel Macias
Date: 2026-09-14
"""
from platformdirs import user_cache_dir
from dataclasses import dataclass,field
from models.catalog import Catalog
import sqlite3
from typing import Optional
from pathlib import Path
import json


@dataclass
class Cache():
    processed: set[str] = field(default_factory=set)

    @classmethod
    def hashes_from_catalog(cls, catalog:Catalog):
        return cls(processed=catalog.get_all_hashes())

    @classmethod
    def hashes_from_objects(cls, catalog:Catalog):
        return cls(processed=catalog.get_object_hashes())
    @classmethod
    def hashes_from_face_boxes(cls,catalog:Catalog):
        return cls(processed=catalog.get_face_box_hashes())

    @classmethod
    def hashes_from_face_landmarks(cls,catalog: Catalog):
        return cls(processed=catalog.hashes_from_face_landmarks())
    

    
    

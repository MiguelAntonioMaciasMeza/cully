"""
File: Cully/modules/models/catalog.py
Description: Defines catalog model that will keep track of photos attributes for persistent storage
Looks at .local/share/cully if directory doesn't exists one will be created. This also creates a
sqlite database that keeps tracks of images by their hash.
Author: Miguel Macias
Date: 2026-09-03
"""

import sqlite3
from dataclasses import dataclass, field
from platformdirs import user_data_dir
from models.photo import Photo
from models.boundingbox import BoundingBox
from typing import Optional, Any
from pathlib import Path


def default_catalog_path() -> str:
    print(user_data_dir("cully") + "/catalog.db")
    return str(user_data_dir("cully") + "/catalog.db")


@dataclass
class Catalog:
    catalog_path: str = field(default_factory=default_catalog_path)
    catalog_connection: Optional[sqlite3.Connection] = field(
        default=None, repr=False, init=False
    )
    cursor: Optional[sqlite3.Cursor] = field(default=None, repr=False, init=False)

    def __post_init__(self):

        Path(self.catalog_path).parent.mkdir(parents=True, exist_ok=True)
        self.catalog_connection = sqlite3.connect(self.catalog_path)
        self.catalog_connection.row_factory = sqlite3.Row
        self.cursor = self.catalog_connection.cursor()

        if not self.catalog_connection:
            raise ValueError("[catalog.py]catalog_connect is requied")
        if not self.cursor:
            raise ValueError("[catalog.py]cursor is required")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY,
                image_path TEXT NOT NULL,
                image_hash TEXT NOT NULL UNIQUE,
                phash TEXT,
                group_id TEXT,
                culled_status TEXT,
                final_score REAL,
                capture_time TEXT,
                camera_model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS bounding_boxes (
            id INTEGER PRIMARY KEY,
            image_hash TEXT NOT NULL,
            confidence REAL,
            model_version TEXT,
            name TEXT,
            x1 INTEGER,
            y1 INTEGER,
            x2 INTEGER,
            y2 INTEGER,
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
            """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS faces(
        id INTEGER PRIMARY KEY,
        image_hash INTEGER,
        embedding BLOB,
        group_id TEXT,
        eye_state TEXT,
        FOREIGN KEY (image_hash) REFERENCES photos(image_hash))
        """)

        self.catalog_connection.commit()

    def insert_photo(self, photo: Photo):
        if self.cursor is None or self.catalog_connection is None:
            print(
                f"[catalog.py]cursor/catalog_connection is not connected\nPath:{self.catalog_path}"
            )
            return
        if self._check_if_photo_exists(photo.image_hash) is True:
            print("[catalog.py]Photo could not be inserted, already exists in catalog")
            return

        self.cursor.execute(
            "INSERT INTO photos (image_path, image_hash) VALUES (?,?)",
            (str(photo.path_to_photo), photo.image_hash),
        )

        self.catalog_connection.commit()

    def _check_if_photo_exists(self, image_hash: str) -> bool:
        if self.cursor is None or self.catalog_connection is None:
            raise RuntimeError("[catalog.py]self.cursor/connection is None")

        self.cursor.execute(
            "SELECT id, image_path FROM photos WHERE image_hash = ?", (image_hash,)
        )

        row = self.cursor.fetchone()
        if row is not None:
            print(f"[catalog.py]Photo[{row['image_path']}] exists at id[{row['id']}]")
            return True

        return False

    def show_row_table_all(self) -> list[Any]:
        if self.cursor is None or self.catalog_connection is None:
            raise RuntimeError("[catalog.py]cursor/catalog_connect is not connected")
        self.cursor.execute("SELECT * FROM photos")
        table = self.cursor.fetchall()
        for row in table:
            for item in row:
                print(item)
        return table

    def insert_bounding_box(self, image_hash: str, boxes: list[BoundingBox]):
        if self.cursor is None or self.catalog_connection is None:
            raise RuntimeError("[catalog.py]cursor/catalog_connection is none")

        self.cursor.executemany(
            """INSERT INTO bounding_boxes (image_hash, model_version, confidence, name, x1, y1, x2, y2)
           VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    image_hash,
                    box.model_version,
                    box.confidence,
                    box.name,
                    box.x1,
                    box.y1,
                    box.x2,
                    box.y2,
                )
                for box in boxes
            ],
        )
        self.catalog_connection.commit()

    def close(self):
        if self.catalog_connection:
            self.catalog_connection.close()

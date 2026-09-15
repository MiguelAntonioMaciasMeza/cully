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

DEBUG = False
def default_catalog_path() -> str:
    return str(user_data_dir("cully") + "/catalog/catalog.db")


@dataclass
class Catalog:
    catalog_path: str = field(default_factory=default_catalog_path)
    catalog_connection: Optional[sqlite3.Connection] = field(
        default=None, repr=False, init=False
    )
    cursor: Optional[sqlite3.Cursor] = field(default=None, repr=False, init=False)

    def __post_init__(self):
        if DEBUG:
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
                x_resolution INTEGER,
                y_resolution INTEGER,
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
        self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS face_boxes(
                id INTEGER PRIMARY KEY,
                parent_box_id INTEGER,
                image_hash INTEGER,
                confidence REAL,
                x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
                FOREIGN KEY (parent_box_id) REFERENCES bounding_box(id)
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
            if DEBUG:
                print("[catalog.py]Photo could not be inserted, already exists in catalog")
            return

        if photo.exif_data is not None:
            if len(photo.exif_data) > 0:
                self.cursor.execute(
            "INSERT INTO photos (image_path, image_hash,capture_time, x_resolution, y_resolution) VALUES (?,?,?,?,?)",
            (str(photo.path_to_photo), photo.image_hash, str(photo.exif_data["datetime_original"]), photo.exif_data["x_resolution"], photo.exif_data["y_resolution"]),
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
            if DEBUG:
                print(f"[catalog.py]Photo[{row['image_path']}] exists at id[{row['id']}]")
            return True

        return False

    def grab_all_rows_from_table(self, table:str)-> list[Any] | None:
        if self.cursor is None or self.catalog_connection is None:
            raise RuntimeError("[catalog.py]cursor/catalog_connection is not connected")

        self.cursor.execute(f"SELECT * FROM {table}")
        results = self.cursor.fetchall()
        
        return results 

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

    def get_boxes_by_name(self, name:str) -> Optional[list[sqlite3.Row]]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        results = self.cursor.execute("SELECT * FROM bounding_boxes WHERE name = ?",(name,)).fetchall()
        return results

    def get_photo_path_by_hash(self, img_hash:str) -> Optional[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute("SELECT image_path FROM photos WHERE image_hash = ?", (img_hash,)).fetchone()
        if row is None:
            if DEBUG:
                print("Photo table does not exist")
            return None
        return row["image_path"]

    def _drop_table(self, table: str):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[cataloy.py] cursor/catalog_connection is None")
        self.cursor.execute(f"SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,) )
        result = self.cursor.fetchone() is not None
        if result is None:
            if DEBUG:
                print(f"Table:{table}, does not exists")
            return
        try:
            self.cursor.execute(f"DROP TABLE ?", (table,))
            self.catalog_connection.commit()
            if DEBUG:
                print(f"table {table} has been dropped")
        except sqlite3.Error as msg:
            if DEBUG:
                print(f"[catalog.py/_drop_table]{msg}")

    def insert_face_box(self, img_hash:str,box: BoundingBox):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        self.cursor.execute("INSERT INTO face_boxes (confidence,image_hash,parent_box_id, x1,y1,x2,y2) VALUES (?,?,?,?,?,?,?)",(box.confidence,img_hash, box.id,box.x1,box.y1,box.x2,box.y2))
        self.catalog_connection.commit()


    def get_all_hashes(self) -> set[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
            


        results = self.cursor.execute("SELECT image_hash FROM photos").fetchall()
        if len(results) == 0:
            if DEBUG:
                print("[catalog.py]No hashes found in photos")
                return set()
        hashes = set()
        for result in results:
            hashes.add(result["image_hash"])

        return hashes

    def get_object_hashes(self) -> set[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")

        results = self.cursor.execute("SELECT image_hash FROM bounding_boxes").fetchall()
        if len(results) == 0:
            if DEBUG:
                print("[catalog.py]No hashes found in bounding_boxes")
                return set()
        hashes = set()
        for result in results:
            if result["image_hash"] not in hashes:
                hashes.add(result["image_hash"])
        return hashes

    def get_face_box_hashes(self) -> set[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")

        results = self.cursor.execute("SELECT image_hash FROM face_boxes").fetchall()
        if len(results) == 0:
            if DEBUG:
                print("[catalog.py]No hashes found in face_boxes")
                return set()
        hashes = set()
        for result in results:
            if result["image_hash"] not in hashes:
                hashes.add(result["image_hash"])
        return hashes

    

    def close(self):
        if self.catalog_connection:
            self.catalog_connection.close()

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
from models.face_landmarks import FaceLandmarks
from models.face_embeddings import FaceEmbeddings
from collections import defaultdict
from typing import Optional, Any
from pathlib import Path
import json

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
        Path(self.catalog_path).parent.mkdir(parents=True, exist_ok=True)
        self.catalog_connection = sqlite3.connect(self.catalog_path)
        self.catalog_connection.row_factory = sqlite3.Row
        self.cursor = self.catalog_connection.cursor()

        if not self.catalog_connection:
            raise ValueError("[catalog.py]catalog_connect is requied")
        if not self.cursor:
            raise ValueError("[catalog.py]cursor is required")
        self.cursor.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS face_boxes(
                id INTEGER PRIMARY KEY,
                model_version TEXT,
                name TEXT,
                parent_box_id INTEGER,
                confidence REAL,
                x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
                FOREIGN KEY (parent_box_id) REFERENCES bounding_boxes(id)
                )
                """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_landmarks(
            face_box_id INTEGER PRIMARY KEY,
            image_hash TEXT,
            eye_blink_left REAL,
            eye_blink_right REAL,
            landmark_scores_json TEXT,
            FOREIGN KEY (face_box_id) REFERENCES face_boxes(id),
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_embeddings(
            face_box_id INTEGER PRIMARY KEY,
            image_hash TEXT,
            model_name TEXT,
            embedding_json TEXT,
            FOREIGN KEY (face_box_id) REFERENCES face_boxes(id),
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
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

        # Photos without EXIF are still inserted (NULL fields) so foreign keys from other tables resolve
        exif = photo.exif_data or {}
        capture_time = exif.get("datetime_original")
        self.cursor.execute(
            """INSERT INTO photos (image_path, image_hash,capture_time, x_resolution, y_resolution)
            VALUES (?,?,?,?,?)""",
            (
                str(photo.path_to_photo),
                photo.image_hash,
                str(capture_time) if capture_time is not None else None,
                exif.get("x_resolution"),
                exif.get("y_resolution"),
            ),
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
        if DEBUG:
            if len(results) == 0:
                print(f"Table {name} is empty")
        return results

    def get_photo_path_by_hash(self, img_hash:str) -> Optional[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute("SELECT image_path FROM photos WHERE image_hash = ?", (img_hash,)).fetchone()
        if row is None:
            if DEBUG:
                print(f"[catalog.py]{img_hash} does not exist in table photos")
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

    def insert_face_box(self,box: BoundingBox) -> int:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        self.cursor.execute("INSERT INTO face_boxes (confidence,model_version,name,parent_box_id, x1,y1,x2,y2) VALUES (?,?,?,?,?,?,?,?)",(box.confidence,box.model_version, box.name, box.id,box.x1,box.y1,box.x2,box.y2))
        self.catalog_connection.commit()
        assert self.cursor.lastrowid is not None
        return self.cursor.lastrowid

    def insert_face_embeddings(self, embeddings: list[FaceEmbeddings]):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        if not embeddings:
            return
        self.cursor.executemany(
            """
            INSERT INTO face_embeddings(face_box_id, image_hash, model_name, embedding_json)
            VALUES (?,?,?,?)
            ON CONFLICT (face_box_id) DO NOTHING
            """,
            [
                (emb.face_box_id, emb.image_hash, emb.model_name, json.dumps(emb.embedding))
                for emb in embeddings
            ],
        )
        self.catalog_connection.commit()

    def get_face_embeddings(self, model_name: Optional[str] = None) -> list[FaceEmbeddings]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        if model_name is None:
            results = self.cursor.execute("SELECT * FROM face_embeddings").fetchall()
        else:
            results = self.cursor.execute(
                "SELECT * FROM face_embeddings WHERE model_name = ?", (model_name,)
            ).fetchall()
        return [FaceEmbeddings.from_sql_row(row) for row in results]

    def get_photos_without_embeddings(self, model_name: str) -> list[tuple[str, str]]:
        """Returns (image_hash, image_path) for photos that have no embedding for model_name yet."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        results = self.cursor.execute(
            """
            SELECT p.image_hash, p.image_path
            FROM photos p
            WHERE NOT EXISTS (
                SELECT 1 FROM face_embeddings fe
                WHERE fe.image_hash = p.image_hash AND fe.model_name = ?
            )
            """,
            (model_name,),
        ).fetchall()
        return [(row["image_hash"], row["image_path"]) for row in results]

    def get_face_embeddings_with_paths(
        self, model_name: str
    ) -> list[tuple[FaceEmbeddings, str, tuple[int, int, int, int]]]:
        """Returns each stored embedding with its source image path and crop box (x1, y1, x2, y2)."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        results = self.cursor.execute(
            """
            SELECT fe.*, p.image_path, fb.x1, fb.y1, fb.x2, fb.y2
            FROM face_embeddings fe
            JOIN photos p ON p.image_hash = fe.image_hash
            JOIN face_boxes fb ON fb.id = fe.face_box_id
            WHERE fe.model_name = ?
            """,
            (model_name,),
        ).fetchall()
        return [
            (
                FaceEmbeddings.from_sql_row(row),
                row["image_path"],
                (row["x1"], row["y1"], row["x2"], row["y2"]),
            )
            for row in results
        ]


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

        results = self.cursor.execute("""
            SELECT DISTINCT image_hash
            FROM face_boxes
            JOIN bounding_boxes ON bounding_boxes.id = face_boxes.parent_box_id 
        """     
        ).fetchall()
        if len(results) == 0:
            if DEBUG:
                print("[catalog.py]No hashes found in face_boxes")

            return set()
        hashes = set()

        for result in results:
            hashes.add(result["image_hash"])
        return hashes

    def get_face_boxes_with_hash(self) -> defaultdict[str,list[BoundingBox]]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        results = self.cursor.execute("SELECT * FROM face_boxes").fetchall()
        
        boxes:defaultdict[int, list[BoundingBox]] = defaultdict(list)
        for index,box in enumerate(results):
            if box["parent_box_id"] is not None:
                boxes[self._get_hash_from_bounding_box_id(box["parent_box_id"])].append(BoundingBox.from_sql_row(box))

        return boxes

    def insert_face_landmarks(self, landmarks: list[FaceLandmarks]):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        if not landmarks:
            return

        self.cursor.executemany(
            """
            INSERT INTO face_landmarks(face_box_id, image_hash, eye_blink_left, eye_blink_right, landmark_scores_json) 
            VALUES (?,?,?,?,?)
            ON CONFLICT (face_box_id) DO NOTHING
            """,
            [
                (landmark.face_box_id, landmark.image_hash, landmark.eye_blink_left,
                landmark.eye_blink_right, json.dumps(landmark.landmark_scores))
                for landmark in landmarks
            ],
        )
        self.catalog_connection.commit()
    def get_face_landmarks(self) -> list[FaceLandmarks]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        results = self.cursor.execute("SELECT * FROM face_landmarks").fetchall()
        face_landmarks: list[FaceLandmarks] = list()

        for row in results:
            face_landmarks.append(FaceLandmarks.from_sql_row(row))
        return face_landmarks          

    def hashes_from_face_landmarks(self) -> set[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        results = self.cursor.execute("SELECT DISTINCT image_hash FROM face_landmarks").fetchall()
        return {row["image_hash"] for row in results}

    def get_image_path_from_box_id(self,parent_id:int):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        image_hash = self.cursor.execute("SELECT image_hash FROM bounding_box WHERE id = (?)",(parent_id,)).fetchone()
        result = self.cursor.execute("SELECT image_path FROM photos WHERE image_hash = (?)", (image_hash,)).fetchone()
        return result
    
    def get_photo_path_and_hash_by_parent_box_id(self,parent_box_id: int) -> tuple[str,str] | None:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute("""
            SELECT p.image_path, p.image_hash
            FROM photos p
            JOIN bounding_boxes bb ON bb.image_hash = p.image_hash
            WHERE bb.id = ?
""",(parent_box_id,)).fetchone()
        return (row["image_path"],row["image_hash"]) if row else None

    def _get_hash_from_bounding_box_id(self,parent_id: int) -> int:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        hash = self.cursor.execute("""
            SELECT image_hash FROM bounding_boxes WHERE
        id = ?        
""",(parent_id,)).fetchone()
        return hash["image_hash"]
        
    
    def close(self):
        if self.catalog_connection:
            self.catalog_connection.close()

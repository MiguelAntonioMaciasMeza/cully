"""
File: Cully/modules/models/catalog.py
Description: Defines catalog model that will keep track of photos attributes for persistent storage
Catalogs live in config.json's catalog_path folder (default .local/share/cully/catalog), made if missing. This also creates a
sqlite database that keeps tracks of images by their hash.
Author: Miguel Macias
Date: 2026-09-03
"""

import sqlite3
from dataclasses import dataclass, field
from config.config import Config
from models.photo import Photo
from models.boundingbox import BoundingBox
from models.face_landmarks import FaceLandmarks
from models.face_embeddings import FaceEmbeddings
from models.photo_group import CapturedPhoto, Event
from models.face_score import FaceScore, RankedPhoto
from models.report_photo import ReportPhoto
from models.photo_face import PhotoFace
from collections import defaultdict
from typing import Optional, Any
from pathlib import Path
from datetime import datetime
import json

DEBUG = False


def default_catalog_path() -> str:
    """Returns back the main catalog: catalog.db in config.json's catalog_path folder"""
    return resolve_catalog_path(None)


def resolve_catalog_path(name: str | Path | None) -> str:
    """Returns back where a --catalog value points.
    None is the main catalog, a bare name (shoot1) is <catalog folder>/shoot1.db, a path is used as given"""
    folder = Path(Config().catalog_path).expanduser()
    if name is None:
        return str(folder / "catalog.db")
    path = Path(name).expanduser()
    #Anything with a folder in it (/tmp/x.db, ./x.db, ../x.db) is a real path
    if any(sep in str(name) for sep in ("/", "\\")):
        return str(path)
    if path.suffix != ".db":
        path = path.with_name(path.name + ".db")
    return str(folder / path)


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
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        self.cursor.execute("PRAGMA foreign_keys = ON")
        self.cursor.execute("PRAGMA journal_mode = WAL")
        self.cursor.execute("PRAGMA busy_timeout = 3000")
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY,
                image_path TEXT NOT NULL,
                image_hash TEXT NOT NULL UNIQUE,
                phash TEXT,
                group_id TEXT,
                culled_status TEXT,
                final_score REAL,
                burst_rank INTEGER,
                eyes_open INTEGER,
                is_candidate INTEGER,
                capture_time TEXT,
                camera_model TEXT,
                x_resolution INTEGER,
                y_resolution INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        # Catalogs created before burst ranking was stored: add its columns
        photo_columns = {
            row["name"] for row in self.cursor.execute("PRAGMA table_info(photos)")
        }
        for column in ("burst_rank", "eyes_open", "is_candidate"):
            if column not in photo_columns:
                self.cursor.execute(f"ALTER TABLE photos ADD COLUMN {column} INTEGER")
        # capture_time is ISO 8601 text, so this index serves time-ordered scans per camera
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_photos_camera_time ON photos(camera_model, capture_time)"
        )
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
        # The report and face lookups join on these columns
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_bounding_boxes_hash ON bounding_boxes(image_hash)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_face_boxes_parent ON face_boxes(parent_box_id)"
        )
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_landmarks(
            face_box_id INTEGER PRIMARY KEY,
            image_hash TEXT,
            eye_blink_left REAL,
            eye_blink_right REAL,
            landmark_scores_json TEXT,
            ear_left REAL,
            ear_right REAL,
            FOREIGN KEY (face_box_id) REFERENCES face_boxes(id),
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
        """)
        # Catalogs created before EAR existed: CREATE TABLE IF NOT EXISTS won't add the columns
        landmark_columns = {
            row["name"]
            for row in self.cursor.execute("PRAGMA table_info(face_landmarks)")
        }
        for column in ("ear_left", "ear_right"):
            if column not in landmark_columns:
                self.cursor.execute(
                    f"ALTER TABLE face_landmarks ADD COLUMN {column} REAL"
                )
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
        # One score per face per method, so rerunning a method overwrites its old score
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS face_scores(
            face_box_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            score REAL,
            PRIMARY KEY (face_box_id, method),
            FOREIGN KEY (face_box_id) REFERENCES face_boxes(id)
            )
        """)
        # Groups are regenerated on every regroup, so their ids aren't stable; user decisions
        # belong on photos.culled_status, never here
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS photo_groups(
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            parent_id INTEGER,
            camera_model TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            best_image_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES photo_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (best_image_hash) REFERENCES photos(image_hash)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS photo_group_members(
            group_id INTEGER NOT NULL,
            image_hash TEXT NOT NULL UNIQUE,
            position INTEGER NOT NULL,
            PRIMARY KEY (group_id, image_hash),
            FOREIGN KEY (group_id) REFERENCES photo_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
        """)
        # Which settings (as a fingerprint, see utils/steps.py) made each photo's objects and faces,
        # so the app can tell when a settings change left them out of date
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS step_runs(
            image_hash TEXT NOT NULL,
            step TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (image_hash, step),
            FOREIGN KEY (image_hash) REFERENCES photos(image_hash)
            )
        """)
        # Same for steps that redo the whole catalog (sharpness, ranking): one row per step
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS catalog_runs(
            step TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.catalog_connection.commit()

    def insert_photo(self, photo: Photo):
        if self.cursor is None or self.catalog_connection is None:
            print(
                f"[catalog.py]cursor/catalog_connection is not connected\nPath:{self.catalog_path}"
            )
            return
        exif = photo.exif_data or {}
        # Stored absolute so the path works from any folder
        image_path = str(photo.path_to_photo.resolve())

        # Known photo: refresh path, camera and size, keep everything else
        if self._check_if_photo_exists(photo.image_hash) is True:
            self.cursor.execute(
                """UPDATE photos SET image_path = ?, camera_model = ?, x_resolution = ?, y_resolution = ?
                WHERE image_hash = ?""",
                (
                    image_path,
                    exif.get("camera_model"),
                    exif.get("x_resolution"),
                    exif.get("y_resolution"),
                    photo.image_hash,
                ),
            )
            self.catalog_connection.commit()
            if DEBUG:
                print("[catalog.py]Photo already in catalog, refreshed its EXIF fields")
            return

        # Photos without EXIF are still inserted (NULL fields) so foreign keys from other tables resolve
        capture_time = exif.get("datetime_original")
        self.cursor.execute(
            """INSERT INTO photos (image_path, image_hash, capture_time, camera_model, x_resolution, y_resolution)
            VALUES (?,?,?,?,?,?)""",
            (
                image_path,
                photo.image_hash,
                # Only a parsed datetime is stored; anything else means the capture time is unknown
                (
                    capture_time.isoformat(timespec="milliseconds")
                    if isinstance(capture_time, datetime)
                    else None
                ),
                exif.get("camera_model"),
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
                print(
                    f"[catalog.py]Photo[{row['image_path']}] exists at id[{row['id']}]"
                )
            return True

        return False

    def grab_all_rows_from_table(self, table: str) -> list[Any] | None:
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

    def get_boxes_by_name(self, name: str) -> Optional[list[sqlite3.Row]]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        results = self.cursor.execute(
            "SELECT * FROM bounding_boxes WHERE name = ?", (name,)
        ).fetchall()
        if DEBUG:
            if len(results) == 0:
                print(f"Table {name} is empty")
        return results

    def get_photo_path_by_hash(self, img_hash: str) -> Optional[str]:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute(
            "SELECT image_path FROM photos WHERE image_hash = ?", (img_hash,)
        ).fetchone()
        if row is None:
            if DEBUG:
                print(f"[catalog.py]{img_hash} does not exist in table photos")
            return None
        return row["image_path"]

    def _drop_table(self, table: str):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        if self.cursor.fetchone() is None:
            if DEBUG:
                print(f"[catalog.py]Table:{table}, does not exist")
            return
        try:
            # Table names can't be SQL parameters; the name was checked above
            self.cursor.execute(f'DROP TABLE "{table}"')
            self.catalog_connection.commit()
            if DEBUG:
                print(f"table {table} has been dropped")
        except sqlite3.Error as msg:
            if DEBUG:
                print(f"[catalog.py/_drop_table]{msg}")

    def insert_face_box(self, box: BoundingBox) -> int:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        self.cursor.execute(
            "INSERT INTO face_boxes (confidence,model_version,name,parent_box_id, x1,y1,x2,y2) VALUES (?,?,?,?,?,?,?,?)",
            (
                box.confidence,
                box.model_version,
                box.name,
                box.id,
                box.x1,
                box.y1,
                box.x2,
                box.y2,
            ),
        )
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
                (
                    emb.face_box_id,
                    emb.image_hash,
                    emb.model_name,
                    json.dumps(emb.embedding),
                )
                for emb in embeddings
            ],
        )
        self.catalog_connection.commit()

    def get_face_embeddings(
        self, model_name: Optional[str] = None
    ) -> list[FaceEmbeddings]:
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

        results = self.cursor.execute(
            "SELECT image_hash FROM bounding_boxes"
        ).fetchall()
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
        """).fetchall()
        if len(results) == 0:
            if DEBUG:
                print("[catalog.py]No hashes found in face_boxes")

            return set()
        hashes = set()

        for result in results:
            hashes.add(result["image_hash"])
        return hashes

    def get_face_boxes_with_hash(self) -> defaultdict[str, list[BoundingBox]] | None:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        results = self.cursor.execute("SELECT * FROM face_boxes").fetchall()

        boxes: defaultdict[str, list[BoundingBox]] = defaultdict(list)
        for index, box in enumerate(results):
            # A box without a person box can't be traced to its photo, so skip it rather than every box
            if box["parent_box_id"] is None:
                print(
                    f"[catalog.py] Skipping face box {box['id']}, it has no parent person box"
                )
                continue
            boxes[self._get_hash_from_bounding_box_id(box["parent_box_id"])].append(
                BoundingBox.from_sql_row(box)
            )

        return boxes

    def insert_face_landmarks(self, landmarks: list[FaceLandmarks]):
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        if not landmarks:
            return

        self.cursor.executemany(
            """
            INSERT INTO face_landmarks(face_box_id, image_hash, eye_blink_left, eye_blink_right, landmark_scores_json,
                ear_left, ear_right)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT (face_box_id) DO NOTHING
            """,
            [
                (
                    landmark.face_box_id,
                    landmark.image_hash,
                    landmark.eye_blink_left,
                    landmark.eye_blink_right,
                    json.dumps(landmark.landmark_scores),
                    landmark.ear_left,
                    landmark.ear_right,
                )
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
        results = self.cursor.execute(
            "SELECT DISTINCT image_hash FROM face_landmarks"
        ).fetchall()
        return {row["image_hash"] for row in results}

    def get_photo_path_and_hash_by_parent_box_id(
        self, parent_box_id: int
    ) -> tuple[str, str] | None:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute(
            """
            SELECT p.image_path, p.image_hash
            FROM photos p
            JOIN bounding_boxes bb ON bb.image_hash = p.image_hash
            WHERE bb.id = ?
""",
            (parent_box_id,),
        ).fetchone()
        return (row["image_path"], row["image_hash"]) if row else None

    def _get_hash_from_bounding_box_id(self, parent_id: int) -> int:
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        hash = self.cursor.execute(
            """
            SELECT image_hash FROM bounding_boxes WHERE
        id = ?        
""",
            (parent_id,),
        ).fetchone()
        return hash["image_hash"]

    def get_photos_by_capture_time(self) -> list[CapturedPhoto]:
        """Returns the photos with a known capture time, ordered per camera so consecutive photos
        are consecutive shots."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        results = self.cursor.execute("""
            SELECT image_hash, image_path, camera_model, capture_time
            FROM photos
            WHERE capture_time IS NOT NULL
            ORDER BY camera_model, capture_time
        """).fetchall()
        return [CapturedPhoto.from_sql_row(row) for row in results]

    def replace_photo_groups(self, events: list[Event]):
        """Replaces every photo group with events and their bursts. Runs as one transaction, so a
        failed regroup leaves the previous groups in place."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        def iso(
            time: datetime,
        ) -> str:  # same format insert_photo stores capture_time in
            return time.isoformat(timespec="milliseconds")

        insert_group = """INSERT INTO photo_groups (kind, parent_id, camera_model, start_time, end_time)
            VALUES (?,?,?,?,?)"""
        with self.catalog_connection:  # commits on success, rolls back on any exception
            self.cursor.execute(
                "DELETE FROM photo_groups"
            )  # cascades to bursts and members
            for event in events:
                self.cursor.execute(
                    insert_group,
                    (
                        "event",
                        None,
                        event.camera_model,
                        iso(event.start_time),
                        iso(event.end_time),
                    ),
                )
                event_id = self.cursor.lastrowid
                for burst in event.bursts:
                    self.cursor.execute(
                        insert_group,
                        (
                            "burst",
                            event_id,
                            burst.camera_model,
                            iso(burst.start_time),
                            iso(burst.end_time),
                        ),
                    )
                    burst_id = self.cursor.lastrowid
                    self.cursor.executemany(
                        "INSERT INTO photo_group_members (group_id, image_hash, position) VALUES (?,?,?)",
                        [
                            (burst_id, photo.image_hash, position)
                            for position, photo in enumerate(burst.photos)
                        ],
                    )

    def insert_face_scores(self, rows: list[tuple[int, str, float]]):
        """Stores (face_box_id, method, score) rows, replacing any older score for the same method."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        if not rows:
            return
        self.cursor.executemany(
            """
            INSERT INTO face_scores (face_box_id, method, score) VALUES (?,?,?)
            ON CONFLICT (face_box_id, method) DO UPDATE SET score = excluded.score
            """,
            rows,
        )
        self.catalog_connection.commit()

    def get_face_scores_for_hashes(
        self, hashes: list[str], method: str, min_confidence: float = 0
    ) -> list[FaceScore]:
        """Returns each scored face in the given photos with its box and EAR (None if no
        landmarks). Faces below min_confidence are left out, which also covers boxes stored
        before the face threshold existed."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        if not hashes:
            return []
        placeholders = ",".join("?" * len(hashes))
        results = self.cursor.execute(
            f"""
            SELECT fs.face_box_id, bb.image_hash, fs.score, fl.ear_left, fl.ear_right,
                fb.x1, fb.y1, fb.x2, fb.y2
            FROM face_scores fs
            JOIN face_boxes fb ON fb.id = fs.face_box_id
            JOIN bounding_boxes bb ON bb.id = fb.parent_box_id
            LEFT JOIN face_landmarks fl ON fl.face_box_id = fs.face_box_id
            WHERE fs.method = ? AND bb.image_hash IN ({placeholders})
                AND fb.name IS NOT 'No Faces Found'  -- the whole person box, not a face
                AND fb.confidence >= ?
            """,
            (method, *hashes, min_confidence),
        ).fetchall()
        return [FaceScore.from_sql_row(row) for row in results]

    def update_burst_ranking(self, ranked: list[RankedPhoto]):
        """Saves each photo's score, rank, eyes open and candidate flags, and marks the rank 1
        photo as its burst's best. The burst is found through photo_group_members, so
        replace_photo_groups must have run first."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        if not ranked:
            return
        best = min(ranked, key=lambda photo: photo.rank)
        with self.catalog_connection:
            self.cursor.executemany(
                """
                UPDATE photos SET final_score = ?, burst_rank = ?, eyes_open = ?, is_candidate = ?
                WHERE image_hash = ?
                """,
                [
                    (
                        photo.score,
                        photo.rank,
                        photo.eyes_open,
                        photo.is_candidate,
                        photo.image_hash,
                    )
                    for photo in ranked
                ],
            )
            self.cursor.execute(
                """
                UPDATE photo_groups SET best_image_hash = ?
                WHERE id = (SELECT group_id FROM photo_group_members WHERE image_hash = ?)
                """,
                (best.image_hash, best.image_hash),
            )

    def clear_burst_ranking(self):
        """Clears every photo's score, rank, eyes open and candidate flags before a new ranking."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        with self.catalog_connection:
            self.cursor.execute("""
                UPDATE photos
                SET final_score = NULL, burst_rank = NULL, eyes_open = NULL, is_candidate = NULL
                """)

    def delete_orphan_face_boxes(self) -> int:
        """Deletes face boxes with no parent person box, plus anything stored on them. Returns how
        many boxes were deleted."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        orphans = "SELECT id FROM face_boxes WHERE parent_box_id IS NULL"
        with self.catalog_connection:
            # Children first, the foreign keys point at face_boxes
            for table in ("face_embeddings", "face_landmarks", "face_scores"):
                self.cursor.execute(
                    f"DELETE FROM {table} WHERE face_box_id IN ({orphans})"
                )
            self.cursor.execute("DELETE FROM face_boxes WHERE parent_box_id IS NULL")
            return self.cursor.rowcount

    def get_report_photos(self, min_face_confidence: float = 0) -> list[ReportPhoto]:
        """Every photo with its event, burst, ranking flags and person/face counts, in event, burst
        then rank order. Photos in no burst (no capture time) come last."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        rows = self.cursor.execute(
            """
            SELECT p.image_hash, p.image_path, p.camera_model, p.capture_time, p.culled_status,
                   p.final_score, p.burst_rank, p.eyes_open, p.is_candidate, p.x_resolution AS width, p.y_resolution AS height,
                   g.id AS burst_id, g.start_time AS burst_start,
                   e.id AS event_id, e.start_time AS event_start, e.end_time AS event_end,
                   (SELECT count(*) FROM bounding_boxes b
                    WHERE b.image_hash = p.image_hash AND b.name = 'person') AS persons,
                   (SELECT count(*) FROM face_boxes f
                    JOIN bounding_boxes b ON b.id = f.parent_box_id
                    WHERE b.image_hash = p.image_hash AND f.name != 'No Faces Found'
                      AND f.confidence >= ?) AS faces
            FROM photos p
            LEFT JOIN photo_group_members m ON m.image_hash = p.image_hash
            LEFT JOIN photo_groups g ON g.id = m.group_id AND g.kind = 'burst'
            LEFT JOIN photo_groups e ON e.id = g.parent_id
            ORDER BY e.start_time IS NULL, e.start_time, g.start_time, p.burst_rank IS NULL, p.burst_rank,
                     m.position, p.capture_time
            """,
            (min_face_confidence,),
        ).fetchall()
        return [ReportPhoto.from_sql_row(row) for row in rows]

    def get_faces_for_photo(
        self, image_hash: str, method: str = "laplacian", min_confidence: float = 0
    ) -> list[PhotoFace]:
        """Real faces in one photo with their sharpness (by method) and EAR, left to right."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        rows = self.cursor.execute(
            """
            SELECT f.id, f.x1, f.y1, f.x2, f.y2, f.confidence,
                   s.score AS sharpness, l.ear_left, l.ear_right
            FROM face_boxes f
            JOIN bounding_boxes b ON b.id = f.parent_box_id
            LEFT JOIN face_scores s ON s.face_box_id = f.id AND s.method = ?
            LEFT JOIN face_landmarks l ON l.face_box_id = f.id
            WHERE b.image_hash = ? AND f.name != 'No Faces Found' AND f.confidence >= ?
            ORDER BY f.x1
            """,
            (method, image_hash, min_confidence),
        ).fetchall()
        return [PhotoFace.from_sql_row(row) for row in rows]

    def get_face_box_with_path(
        self, face_box_id: int
    ) -> tuple[str, str, tuple[int, int, int, int]] | None:
        """Photo path, image hash and (x1, y1, x2, y2) of one real face box, None if there is no such face."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")
        row = self.cursor.execute(
            """
            SELECT p.image_path, p.image_hash, f.x1, f.y1, f.x2, f.y2
            FROM face_boxes f
            JOIN bounding_boxes b ON b.id = f.parent_box_id
            JOIN photos p ON p.image_hash = b.image_hash
            WHERE f.id = ? AND f.name != 'No Faces Found'
            """,
            (face_box_id,),
        ).fetchone()
        if row is None:
            return None
        return row["image_path"], row["image_hash"], (row["x1"], row["y1"], row["x2"], row["y2"])

    def set_culled_status(self, image_hash: str, status: str | None) -> bool:
        """Sets culled status of an image"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog connection is None")
        valid_status = {"keep", "reject", None}
        if status not in valid_status:
            raise ValueError(
                f"[catalog.py]set_culled_status recieved invalid status: {status}"
            )
        if not self._check_if_photo_exists(image_hash):
            return False

        self.cursor.execute(
            "UPDATE photos SET culled_status = ? WHERE image_hash = ? ",
            (status, image_hash),
        )
        self.catalog_connection.commit()
        return True

    def accept_burst(self, burst_id: int) -> tuple[int, int] | None:
        """Marks a burst's candidates keep and its other ranked photos reject. Returns (kept, rejected), None if no such burst."""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py]cursor/catalog_connection is None")

        with self.catalog_connection:
            row = self.cursor.execute("SELECT 1 FROM photo_groups WHERE id = ? AND kind = 'burst'",(burst_id,),).fetchone()
            if row is None:
                return None

            self.cursor.execute(
                """
            UPDATE photos SET culled_status = 'keep' 
            WHERE image_hash IN (SELECT image_hash FROM photo_group_members 
            WHERE group_id = ?) 
            AND culled_status IS NULL 
            AND burst_rank IS NOT NULL 
            AND is_candidate = 1 
            """, 
            (burst_id,),)

            kept = self.cursor.rowcount
            self.cursor.execute(""" 
                UPDATE photos SET culled_status = 'reject'
                WHERE image_hash IN (SELECT image_hash FROM photo_group_members WHERE group_id = ?)
                    AND culled_status IS NULL
                    AND burst_rank IS NOT NULL
                    AND is_candidate IS NOT 1
                    """, (burst_id,),)
            rejected = self.cursor.rowcount
            return kept, rejected

    def _processed_hashes(self, step: str) -> set[str]:
        """Returns back the photos step has stored results for (marker rows count)"""
        if step == "objects":
            return self.get_object_hashes()
        if step == "faces":
            return self.get_face_box_hashes()
        raise ValueError(f"[catalog.py] {step} isn't tracked per photo")

    def record_step_runs(self, step: str, hashes: set[str] | list[str], fingerprint: str) -> None:
        """Records that step just ran on hashes with the settings behind fingerprint"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        with self.catalog_connection:
            self.cursor.executemany(
                "INSERT OR REPLACE INTO step_runs (image_hash, step, fingerprint, ran_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                [(image_hash, step, fingerprint) for image_hash in hashes],
            )

    def record_catalog_run(self, step: str, fingerprint: str) -> None:
        """Records that a whole-catalog step (sharpness, ranking) just ran with fingerprint's settings"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        with self.catalog_connection:
            self.cursor.execute(
                "INSERT OR REPLACE INTO catalog_runs (step, fingerprint, ran_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (step, fingerprint),
            )

    def catalog_run_fingerprint(self, step: str) -> str | None:
        """Returns back the fingerprint step last ran with, None if it never ran since tracking began"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        row = self.cursor.execute("SELECT fingerprint FROM catalog_runs WHERE step = ?", (step,)).fetchone()
        return row["fingerprint"] if row else None

    def start_tracking(self, fingerprints: dict[str, str]) -> bool:
        """The first time only: records everything already processed as made with fingerprints
        (step -> fingerprint), so older photos aren't flagged. Returns back True if it did that now"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        if self.catalog_run_fingerprint("tracking_started") is not None:
            return False
        for step in ("objects", "faces"):
            self.record_step_runs(step, self._processed_hashes(step), fingerprints[step])
        #Only claim ranking ran if it left something behind
        ranked = self.cursor.execute("SELECT 1 FROM photo_groups LIMIT 1").fetchone()
        if ranked:
            for step in ("sharpness", "ranking"):
                self.record_catalog_run(step, fingerprints[step])
        self.record_catalog_run("tracking_started", "-")
        return True

    def processed_photos(self, step: str) -> set[str]:
        """Returns back every photo step has results for, current or not"""
        return self._processed_hashes(step)

    def stale_photos(self, step: str, fingerprint: str) -> set[str]:
        """Returns back photos whose step results were made with other settings than fingerprint"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        current = {
            row["image_hash"]
            for row in self.cursor.execute(
                "SELECT image_hash FROM step_runs WHERE step = ? AND fingerprint = ?", (step, fingerprint)
            )
        }
        #Processed but with no matching record also counts, it can't be shown to be current
        return self._processed_hashes(step) - current

    def delete_detections(self, hashes: set[str] | list[str], step: str) -> int:
        """Deletes what step and the steps after it stored for hashes, so the next run redoes them.
        objects: person/object boxes and everything below. faces: face boxes and below, person boxes stay.
        Never touches culled_status. Returns back how many photos were cleared"""
        if self.cursor is None or self.catalog_connection is None:
            raise ValueError("[catalog.py] cursor/catalog_connection is None")
        if step not in ("objects", "faces"):
            raise ValueError(f"[catalog.py] can't redo {step}, only objects or faces")
        hashes = list(hashes)
        cursor = self.cursor
        with self.catalog_connection:
            # A temp table keeps the IN lists short however many photos there are
            cursor.execute("CREATE TEMP TABLE IF NOT EXISTS redo_hashes (image_hash TEXT PRIMARY KEY)")
            cursor.execute("DELETE FROM redo_hashes")
            cursor.executemany("INSERT OR IGNORE INTO redo_hashes VALUES (?)", [(h,) for h in hashes])
            faces = """SELECT f.id FROM face_boxes f JOIN bounding_boxes b ON b.id = f.parent_box_id
                       WHERE b.image_hash IN (SELECT image_hash FROM redo_hashes)"""
            #Children first, the foreign keys are on
            cursor.execute(f"DELETE FROM face_landmarks WHERE face_box_id IN ({faces})")
            cursor.execute(f"DELETE FROM face_embeddings WHERE face_box_id IN ({faces})")
            cursor.execute(f"DELETE FROM face_scores WHERE face_box_id IN ({faces})")
            cursor.execute(f"DELETE FROM face_boxes WHERE id IN ({faces})")
            redone = ["faces"]
            if step == "objects":
                cursor.execute("DELETE FROM bounding_boxes WHERE image_hash IN (SELECT image_hash FROM redo_hashes)")
                redone.append("objects")
            cursor.executemany(
                "DELETE FROM step_runs WHERE step = ? AND image_hash IN (SELECT image_hash FROM redo_hashes)",
                [(name,) for name in redone],
            )
            cursor.execute("DELETE FROM redo_hashes")
        return len(hashes)

    def close(self):
        if self.catalog_connection:
            self.catalog_connection.close()

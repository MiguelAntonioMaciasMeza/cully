import cv2
from pathlib import Path
from models.catalog import Catalog
from models.boundingbox import BoundingBox
from collections import defaultdict
from utils.read_image import read_image

OUT_DIR = Path("/home/ripley/Documents/FinalRepo/Unused Images/People/Face_boxes")


def draw_face_boxes(image_path: Path, boxes: list[BoundingBox]) -> None:
    image = read_image(image_path)
    if image is None:  # missing or unreadable file
        print(f"[SKIP] could not read {image_path}")
        return

    thickness = max(2, image.shape[1] // 400)  # scale with image width
    for box in boxes:
        cv2.rectangle(image, (box.x1, box.y1), (box.x2, box.y2), (0, 255, 0), thickness)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT_DIR / f"{image_path.stem}.jpg"), image)


def main():
    catalog = Catalog()
    try:
        boxes_by_image: dict[str, list[BoundingBox]] = defaultdict(list)

        for parent_box_id, boxes in catalog.get_face_boxes().items():
            result = catalog.get_photo_path_and_hash_by_parent_box_id(parent_box_id)
            if result is None:
                continue
            boxes_by_image[result[0]].extend(boxes)

        for path, boxes in boxes_by_image.items():
            draw_face_boxes(Path(path), boxes)
    finally:
        catalog.close()
if __name__ == "__main__":
    main()
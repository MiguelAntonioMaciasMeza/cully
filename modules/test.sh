#!/bin/bash
# Runs each module's smoke test with the venv it depends on: venv-main for YOLO/torch,
# venv-faces for mediapipe/DeepFace. Re-sourcing a venv's activate script already
# deactivates whatever venv is currently active, so no explicit `deactivate` is needed.
cd "$(dirname "${BASH_SOURCE[0]}")"

echo -e "------------------Beginning scanner test------------------"
python3 -m ingest.directory_scanner_test
echo -e "------------------Directory scanner test complete------------------"

source /home/ripley/Documents/FinalRepo/Cully/venv-main/bin/activate

echo -e "------------------Beginning object test------------------"
python3 -m detector.object_test
echo -e "------------------Object test complete------------------"

source /home/ripley/Documents/FinalRepo/Cully/venv-faces/bin/activate

echo -e "------------------Beginning face detect test------------------"
python3 -m detector.face_detect_test
echo -e "------------------Finished face detect test------------------"

echo -e "------------------Beginning face landmarker detect test------------------"
python3 -m detector.face_landmarker_test
echo -e "------------------Finished face landmarker test------------------"

echo -e "------------------Beginning face embeddings test------------------"
python3 -m detector.face_embeddings_test
echo -e "------------------Finished face embeddings test------------------"

echo -e "------------------Beginning face grouping test------------------"
python3 -m detector.face_grouping_test
echo -e "------------------Finished face grouping test------------------"

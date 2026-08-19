import cv2
import numpy
import torch
import os
from ultralytics import YOLO
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))

script_dir = os.path.dirname(os.path.abspath(__file__))
path_to_image = os.path.join(script_dir,"Images","IMG_8305.jpg")

model = YOLO("yolo26n.pt")
results = list(model(path_to_image))
if results is None or results[0].boxes is None or len(results[0].boxes) == 0:
    raise ValueError("Yolo didn't detect anything")
class_names = list()
for result in results:
    class_names = result.names 

for box in results[0].boxes:
    class_id = int(box.cls[0])
    label = class_names[class_id]
    cords = box.xyxy[0].tolist()


print(label)
x_start,y_start, x_end, y_end  =  int(cords[0]), int(cords[1]) , int(cords[2]), int(cords[3])

print(cords)
image = cv2.imread(path_to_image)
if image is None:
    raise FileNotFoundError("Couldn't load JPG")
#Crop image to only check sharpness in bounding box
gray_image = image[y_start:y_end, x_start:x_end]
gray_image = cv2.cvtColor(gray_image, cv2.COLOR_BGR2GRAY)

sharpness = cv2.Laplacian(gray_image,cv2.CV_64F).var()
#Resize the image
cv2.rectangle(image, (x_start, y_start),(x_end,y_end),(0,0,255), 10)
cv2.namedWindow("Resized Window", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Resized Window", 1920, 1080)
cv2.imshow("Resized Window",image)
print(sharpness)
cv2.waitKey(0)

cv2.imshow("Resized Window", gray_image)
cv2.waitKey(0)



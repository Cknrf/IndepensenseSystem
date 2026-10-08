"""The detector's class list: index order is the model's contract."""

CLASSES = [
    # COCO, kept for a blind pedestrian (index order irrelevant to COCO's own)
    "person", "bicycle", "car", "motorcycle", "bus", "truck", "traffic_light",
    "stop_sign", "bench", "dog", "cat", "chair", "couch", "bed", "dining_table",
    "toilet", "tv", "laptop", "cell_phone", "bottle", "cup", "backpack",
    "umbrella", "potted_plant", "fire_hydrant",
    # Open Images V7
    "door", "stairs",
    # Philippine / street hazards
    "jeepney", "tricycle", "pedicab", "pushcart", "open_manhole", "pothole",
]
IDX = {c: i for i, c in enumerate(CLASSES)}

# COCO 80-class index -> our key
COCO_NAMES = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse",
    "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie",
    "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut",
    "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]
COCO_TO_OURS = {i: IDX[n.replace(" ", "_")] for i, n in enumerate(COCO_NAMES) if n.replace(" ", "_") in IDX}

# Source label -> our key, chosen from crop sheets of each source class (see report).
# A label mapped to None is dropped: its boxes are removed, the image kept.
SOURCE_MAPS = {
    "kaggle_dlsud": {
        "Bicycle": "bicycle", "Electric Bike": "tricycle", "Hatchback": "car", "Large Bus": "bus",
        "Light Goods Vehicle": "truck", "Medium Goods Vehicle": "truck", "Motorcycle": "motorcycle",
        "Pickup Truck": "truck", "Public Utility Jeepney": "jeepney", "Sedan": "car", "Small Bus": "bus",
        "Sports Utility Vehicle": "car", "Tricycle": "tricycle", "Van": "car"},
    "rf_g17-datasets_v3": {
        "ambulance": "car", "bicycle": "bicycle", "bus": "bus", "car": "car", "ev_large": "tricycle",
        "ev_small": "motorcycle", "firetruck": "truck", "jeepney": "jeepney", "kalesa": None,
        "kariton": "pushcart", "motorcycle": "motorcycle", "pedicab": "pedicab", "police_car": "car",
        "tricycle": "tricycle", "truck": "truck", "tuktuk": "tricycle", "van": "car"},
    "rf_ph-vehicles-728sm_v5": {
        "Bicycle": "bicycle", "Bus": "bus", "Car": "car", "E-Jeep": "bus", "E-bike": "tricycle",
        "Jeepney": "jeepney", "Motorcycle": "motorcycle", "Tricycle": "tricycle", "Truck": "truck", "Van": "car"},
    "rf_cityfix-projects2_v5": {
        "closed manhole": None, "improperly closed manhole": "open_manhole",
        "open manhole": "open_manhole", "pothole": "pothole"},
}

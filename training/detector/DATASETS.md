# Training data — sources, versions, licences

The detector in `models/detector/` was trained on the sources below. CC BY 4.0
requires attribution; this file is that attribution, and the thesis should
reproduce it. Roboflow projects can be edited or deleted by their owners, so
the exported version and fetch date are recorded.

| Source | Version / fetched | Licence | Used for |
|---|---|---|---|
| Jan Carlo Paredes, *philippine-vehicle-classification-14class* (DLSU-Dasmariñas), https://www.kaggle.com/datasets/jancarloparedes/philippine-vehicle-classification-14class | 2026-10-07 | CC BY 4.0 | jeepney, tricycle (incl. e-trikes), car, bus, truck, motorcycle, bicycle |
| Groups Workspace, *G17 Datasets*, https://universe.roboflow.com/groups-workspace/g17-datasets | v3, 2026-10-07 | CC BY 4.0 | jeepney, tricycle, pedicab, pushcart (kariton), vehicles |
| vehicle-detection-and-data-generation, *PH Vehicles*, https://universe.roboflow.com/vehicle-detection-and-data-generation/ph-vehicles-728sm | v5, 2026-10-07 | CC BY 4.0 | jeepney, tricycle, e-jeep (as bus), vehicles |
| inacap-rp6mt, *CityFix Projects2*, https://universe.roboflow.com/inacap-rp6mt/cityfix-projects2 | v5, 2026-10-07 | CC BY 4.0 | open manhole, pothole |
| COCO 2017, https://cocodataset.org | train/val 2017 | Annotations CC BY 4.0 (COCO Consortium); images under Flickr terms, per-image licence in the annotation JSON | 25 everyday classes, replay against forgetting |
| Open Images V7, https://storage.googleapis.com/openimages/web/index.html | train | Annotations CC BY 4.0 (Google); images listed as CC BY 2.0 | door, stairs |

Model weights derived from Ultralytics YOLO26n are AGPL-3.0
(https://www.ultralytics.com/license) — fine for this open-source thesis
repository; a closed or commercial build would need an Ultralytics
Enterprise licence.

Teacher models used only to label training data (not shipped): Ultralytics
`yolo26x` and `yoloe-26x-seg`, AGPL-3.0.

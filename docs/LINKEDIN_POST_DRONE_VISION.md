# LinkedIn post draft — drone detection and visual family experiment

Copy the text below into LinkedIn and attach both images. The images are real
MMAUD V1 held-out test frames, processed offline by the existing detector and
the separate experimental family classifier. Image attribution and license:
[MMAUD attribution](MMAUD_ATTRIBUTION.md).

## Copy-ready post

I wanted my drone-detection project to do more than draw a box. I added a
separate visual classifier and evaluated the two-stage pipeline on real,
wide-angle drone footage from MMAUD V1.

The experiment covers five sequence-labeled types: Mavic 2, Mavic 3, Phantom 4,
Avata, and M300. The official test segments were excluded from training, and I
evaluated 584 labeled test crops. These segments come from flights also present
in training, so this test does not prove generalization to new scenes.

Here is what the numbers actually say:

- Classifier-only accuracy across the five labels: **51.4%**.
- After grouping Mavic 2 and Mavic 3 into the Mavic family: **58.7%** across
  Mavic, Phantom, Avata, and M300.
- On the narrower shared Mavic/Phantom subset (338 crops), the new candidate
  scored **78.7%**, compared with **20.1%** for the previous classifier.
- In the full detector-plus-classifier pipeline, the detector missed **78.1%**
  of the test targets. Only **63 of 584 (10.8%)** received the correct family
  label end to end.

So the 80% real-world goal is **not met**. The strongest lesson is that small,
distant-object detection is currently the bottleneck. A classifier cannot name
a drone that the detector never finds, and several Avata examples were confused
with other families.

The next step is to improve small-object detection and test on separate scenes,
then rerun the full evaluation. The candidate remains separate from the
production checkpoint; visual family predictions are experimental evidence,
not a registered drone identity.

This is a useful computer-vision result even without a victory metric: the
held-out test exposed exactly where the pipeline fails and what to improve next.

Dataset: MMAUD, Yuan et al., ICRA 2024. The attached frames are from its V1
test segments and are shared with attribution under CC BY-NC-SA 4.0.

#ComputerVision #ObjectDetection #MachineLearning #DroneDetection #MLOps

## Images to attach

### Correct M300 example

One held-out test frame where YOLO detects the drone and the candidate
classifier predicts M300. The zoom inset enlarges the same frame region; this
single example is illustrative, not an accuracy estimate.

![MMAUD held-out M300 detection and family prediction](../screenshots/mmaud-m300-heldout-hit.jpg)

### Phantom 4 detector miss

One held-out Phantom 4 frame where the detector misses the labeled target. The
red inset shows the ground-truth region that the detector failed to find.

![MMAUD held-out Phantom 4 detector miss](../screenshots/mmaud-phantom4-heldout-miss.jpg)

## Posting note

The dataset is licensed CC BY-NC-SA 4.0. Keep the attribution with these images
and confirm the license is appropriate before using them in commercial
promotion.

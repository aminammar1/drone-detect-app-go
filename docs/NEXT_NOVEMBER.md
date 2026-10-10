# November project plan

This plan is based on the experiments completed on 2026-10-10. The immediate goal is to make drone detection and the limits of visual naming clear, then improve the measured failure points. Do not promise that the system can name every drone.

## What the project currently does

- YOLO detects and tracks drone-shaped objects in images and video. Detection labels and confidence scores do not identify a product model.
- The Go server can resolve a registered drone from an explicit identifier or a Remote ID beacon, check zone authorization in MongoDB, notify alert clients, and export records to Sheets or CSV.
- The visual family classifier is optional experimental evidence. It does not establish a drone's registered identity.

## What the experiments showed

- MMAUD V1 supplied 4,427 wide-angle frames. The evaluation used 584 held-out crops and five sequence-labeled classes: Mavic 2, Mavic 3, Phantom 4, Avata, and M300.
- The candidate classifier got 51.4% exact-class accuracy. Merging Mavic 2 and Mavic 3 raised the score to 58.7% across four families.
- The detector missed 78.1% of test targets. With misses counted, only 10.8% of the test drones received the correct family end to end.
- Many test drones were only about 14–20 pixels across. The test segments were held out in time, but came from flights also represented in training. Performance on new scenes is unknown.
- The candidate was not promoted. The production `family.pt` checkpoint was left unchanged. The project has not demonstrated reliable model naming on arbitrary images, video, or a live camera.

Full metrics and reproduction steps are in [MMAUD_REPORT.md](./MMAUD_REPORT.md) and [MMAUD_EVALUATION.json](./MMAUD_EVALUATION.json).

## Recommended order of work

### 1. Keep a reproducible baseline

Record the current detector, classifier, data split, and end-to-end results before changing weights. Keep the test denominator inclusive of detector misses. Do not compare models only on crops the detector happened to find.

### 2. Improve small-drone detection first

Compare high-resolution or tiled inference with fine-tuning the detector on labeled drone boxes. Use the existing MMAUD test segment for a first comparison, then obtain a separate-scene test set before making a generalization claim. Track recall, false positives, and miss rate by target size.

### 3. Define a realistic visual-name catalog

Start with a short, explicit catalog supported by labeled examples. Merge Mavic 2 and Mavic 3 into a Mavic family unless closer views and new data support separating them. Add an `Unknown` result for unsupported or uncertain crops. Do not label a guess as an exact model name.

The current MMAUD experiment is not enough to train a useful catalog: Avata was almost never recognized, and its test scenes overlap with the training flights. Add clear views across distance, angle, lighting, and different locations. Keep whole flights or locations out of training when creating the final test split. Check the license and attribution before adding any dataset.

### 4. Evaluate before integrating

Report classifier accuracy on labeled crops and end-to-end accuracy on all labeled drone instances. Include detector misses, `Unknown` predictions, false detections, and results for each supported family. Keep the classifier out of production until it performs consistently on a separate scene set.

### 5. Verify the complete demo

Use the files already in `images/` and `videos/` as read-only inputs. Confirm that video playback can be stopped with the window controls and that processing does not block closing the preview. Test a real camera only when one is available. Exercise the authorization and export paths with the simulator and fake exporter; separately verify a real Google Sheets connection if credentials are configured.

## Identity boundary

Pixels can suggest a visual family only when the drone is visible and the model belongs to the trained catalog. Pixels alone cannot reliably identify every make and model, or prove which registered aircraft is flying. Use a serial number or Remote ID matched against the registry for that identity. Treat visual classification as supporting evidence.

## Storage and release rules

- Keep datasets, crops, run directories, and checkpoints out of Git. Inspect their sizes before cleanup; do not remove source media or final weights by assumption.
- Never commit `.env`, credentials, model weights, `data/`, `images/`, or `videos/` content.
- Do not publish project materials or push changes to GitHub unless explicitly requested.
- Avoid a broad dependency upgrade as the first task. Upgrade dependencies only when a specific fix or compatibility need requires it.

## First session

1. Re-run the recorded MMAUD evaluation and preserve the JSON result.
2. Measure detector recall by target size on the same test frames.
3. Compare high-resolution and tiled inference without changing the production checkpoint.
4. Choose whether the next data effort is cross-scene footage for the existing families or clearer labeled examples for a smaller catalog.
5. Review results before deciding whether to train and integrate a new checkpoint.

# Attribution — MMAUD data used in this experiment

- **Dataset:** MMAUD — A Comprehensive Multi-Modal Anti-UAV Dataset for Modern
  Miniature Drone Threats (Yuan et al., ICRA 2024).
- **Sources:** https://github.com/ntu-aris/MMAUD and the public
  `MMAUD_2D` Google Drive folder linked from that README
  (2D-detection baseline: `MMAUD_2D.zip`, 4.37 GiB, plus a `result/` folder
  with the authors' YOLOv5m training curves).
- **License:** [Creative Commons Attribution-NonCommercial-ShareAlike 4.0
  International](https://creativecommons.org/licenses/by-nc-sa/4.0/) —
  non-commercial academic use only. No commercial use is made here; this is a
  local, non-commercial experiment.
- **Citation (as requested by the authors):**
  `@INPROCEEDINGS{yuan2024MMAUD, author={Yuan, Shenghai and Yang, Yizhuo and
  Nguyen, Thien Hoang and Nguyen, Thien-Minh and Yang, Jianfei and Liu, Fen
  and Li, Jianping and Wang, Han and Xie, Lihua}, booktitle={2024 IEEE
  International Conference on Robotics and Automation (ICRA)},
  title={MMAUD: ... Modern Miniature Drone Threats}, year={2024},
  pages={2745-2751}, doi={10.1109/ICRA57147.2024.10610957}}`
- **Label mapping used (from the authors' `MMAUD_2D/README.md`):**
  b1 = Mavic 2, b2 = Mavic 3, b3 = Phantom 4, b4 = Avata, b5 = M300.
- **Derived artifacts** (crops, checkpoints, metrics under `data/training/`)
  are built from this data; per the ShareAlike term, share them alike with
  this attribution preserved.
- Nothing was bypassed: only the publicly link-shared files were downloaded
  (`gdown`, ephemeral use, never added to project dependencies).

# LinkedIn showcase post — Drone Detect App

## Copy-ready post

🚁 **Drone Detect App — from camera detection to airspace decision**

I built an end-to-end drone monitoring prototype that brings computer vision and backend decision-making together.

It detects and tracks drones in images and video, streams events to a Go backend, checks Remote ID against registered aircraft and authorization rules, and records results in MongoDB with Sheets/CSV reporting.

I also experimented with visual drone-family classification as the next step for making detections more informative.

Built with Python, YOLO, OpenCV, Go, Gin, WebSockets, and MongoDB. Still improving it one real test at a time.

Code and project details: [GitHub repository](https://github.com/aminammar1/drone-detect-app-go)

#ComputerVision #DroneDetection #Python #Golang #MachineLearning #OpenSource

## Screenshot to attach

Attach this detector output as the post image:

![YOLO detects a DJI Mavic 3 in a showcase image](../screenshots/showcase-drone-web-dji-mavic-3.jpg)

The box is the model's drone detection. It does not predict the Mavic 3 name; visual family recognition is still being explored. The photo is by HKesteloo, CC BY-SA 4.0: https://commons.wikimedia.org/wiki/File:DJI_Mavic_3.jpg

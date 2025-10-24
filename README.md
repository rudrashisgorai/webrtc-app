# RT-linux-assigment

> Real-Time Programming with Linux (Assignment 3‑b)  
> https://github.com/rudrashisgorai/RT-linux-assigment

## Overview  
Wrap POSIX threads into C++ classes to practice:
- RT vs. non‑RT threads (`SCHED_FIFO`, `SCHED_RR`)
- CPU‑affinity control
- Wall‑time measurement
- A CannyP3 OpenCV workload

## Repo & Clone
```bash
git clone https://github.com/rudrashisgorai/RT-linux-assigment.git
cd RT-linux-assigment
```

## Project Structure
```
.
├── canny_util.c/.h     # Canny filter helper
├── p3_util.cpp/.h      # compute‑intense workloads
├── p3.cpp              # ThreadRT/ThreadNRT & Application classes + main
├── Makefile            # build & link (pthread + OpenCV4)
└── README.md           # this file
```

## Prerequisites  
- Linux (RT threads require sudo)  
- g++ & gcc  
- pkg-config  
- OpenCV 4 & pthreads

## Build & Run
```bash
make
sudo ./p3 [exp_id]
```

## License  
MIT
# webrtc-app

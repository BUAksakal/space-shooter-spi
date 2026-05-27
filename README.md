<div align="center">

# 🚀 Space Shooter via SPI
<div align="center">

<img width="120" alt="THD Logo" src="assets/thd_logo.png" />

**A distributed real-time multiplayer game running on two Raspberry Pi 1 Model B+ nodes**  
**communicating over a hardware SPI bus at 1 MHz.**

![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-1%20Model%20B+-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white)
![SPI](https://img.shields.io/badge/Protocol-SPI%201MHz-brightgreen?style=flat-square)
![FPS](https://img.shields.io/badge/Target-30%20FPS-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

<br/>

> **THD Campus Cham** · Faculty of Applied Natural Sciences and Industrial Engineering  
> Course: *Case Study Edge Device Architecture* · Semester: 26_SS · Group: A06

<br/>

</div>

---

## 📖 Overview
<div align="center">
<img width="680" alt="demo" src="https://github.com/user-attachments/assets/ff97c71b-29d7-49a1-a3d6-daf4b166e6d5" />
</div>

**Space Shooter via SPI** is a 1v1 space shooter game built entirely on embedded hardware — no networking stack, no WiFi, no TCP/IP. Two Raspberry Pi 1 nodes are connected directly at the hardware level via a 4-wire SPI bus, achieving deterministic sub-millisecond latency that no wireless protocol can match.

The project demonstrates a real distributed edge computing architecture: one node acts as the authoritative game engine while the second acts as a dedicated input processor — mirroring the Master-Slave topology used in industrial embedded systems.

---

## ✨ Features

- 🎮 **1v1 Real-Time Multiplayer** — two players, one screen, zero lag
- ⚡ **Hardware SPI Communication** — direct Pi-to-Pi link at 1 MHz, bypassing the OS network stack entirely
- 🔒 **Data Integrity** — 8-bit XOR checksum on every 9-byte SPI packet
- 🛡️ **Dead Reckoning** — automatic motion estimation if the SPI link is interrupted for more than 2 frames
- 📊 **Live Data Logging** — CPU temperature, FPS, SPI latency, and game events logged to CSV on MicroSD
- 🕹️ **30 FPS Deterministic Loop** — fixed 33.3 ms execution window, every frame
- 🖥️ **Portable Display** — 3.5" ILI9486 resistive touchscreen driven directly from Pi A

---

## 🏗️ System Architecture

```
┌─────────────────────────────────┐         ┌─────────────────────────────┐
│         Pi A — MASTER           │         │        Pi B — SLAVE         │
│                                 │         │                             │
│  ┌─────────────────────────┐    │         │   ┌─────────────────────┐   │
│  │      Game Engine        │    │  SPI0   │   │   Input Processor   │   │
│  │  Physics · Collision    │◄──────────────►  │   Joystick · GPIO   │   │
│  │  Rendering · Scoring    │    │  1 MHz  │   │   Packet Builder    │   │
│  └─────────────────────────┘    │         │   └─────────────────────┘   │
│                                 │         │                             │
│  ┌──────────┐  ┌─────────────┐  │         │   ┌─────────────────────┐   │
│  │ 3.5" LCD │  │ P1 Joystick │  │         │   │    P2 Joystick      │   │
│  │ ILI9486  │  │  I2C ADC    │  │         │   │     I2C ADC         │   │
│  └──────────┘  └─────────────┘  │         │   └─────────────────────┘   │
│                                 │         │                             │
│  ┌──────────┐                   │         │   ┌─────────────────────┐   │
│  │ MicroSD  │ game_log.csv      │         │   │     MicroSD         │   │
│  └──────────┘                   │         │   └─────────────────────┘   │
└─────────────────────────────────┘         └─────────────────────────────┘
                    │                                       │
                    └───────────── COMMON GND ──────────────┘
```

### Why SPI over WiFi?

| Property | WiFi / TCP | SPI (This Project) |
|---|---|---|
| Latency | 5–50 ms (variable) | < 1 ms (deterministic) |
| Jitter | High | Near-zero |
| Stack overhead | OS network layers | Hardware direct |
| Reliability | Packet loss possible | Synchronous clock |
| Setup complexity | High | 5 wires |

---

## 🔧 Hardware

### Components

| Component | Quantity | Notes |
|---|---|---|
| Raspberry Pi 1 Model B+ | 2 | BCM2835, ARMv6 700MHz, 512MB RAM |
| 3.5" ILI9486 Resistive Touchscreen | 1 | Connected to Pi A via SPI |
| Analog Joystick Module | 2 | 3.3V, read via I2C ADC |
| MicroSD Card | 2 | OS + game assets + logs |
| USB Power Supply 5V/3A | 2 | One per Pi |
| Jumper Wires | 5 | SPI bus interconnect |

### SPI Wiring — Pi A ↔ Pi B

```
Pi A (Master)                           Pi B (Slave)
─────────────                           ────────────
Pin 23 │ GPIO11 │ SCLK  ──────────────► Pin 23 │ GPIO11 │ SCLK
Pin 19 │ GPIO10 │ MOSI  ──────────────► Pin 19 │ GPIO10 │ MOSI
Pin 21 │ GPIO9  │ MISO  ◄────────────── Pin 21 │ GPIO9  │ MISO
Pin 24 │ GPIO8  │ CE0   ──────────────► Pin 24 │ GPIO8  │ CE0
Pin 6  │ GND    │ GND   ══════════════  Pin 6  │ GND    │ GND
```

> ⚠️ **Critical:** All GPIO signals operate at **3.3V**. Never connect 5V to any GPIO pin — permanent damage will occur.

### Circuit Diagram
https://github.com/user-attachments/files/28310119/19may_sikcuk.pdf
---

## 🎮 Game Loop — How It Works

Every **33.3 ms** (30 FPS), the Master Pi executes the following sequence:

```
┌─────────────────────────────────────────────┐
│              MASTER GAME LOOP               │
│                 (33.3 ms)                   │
├─────────────────────────────────────────────┤
│  1. Read P1 joystick (X, Y, Shoot, Menu)    │
│  2. Fetch P2 data via SPI from Pi B         │
│  3. Update ship positions + boundary check  │
│  4. Move bullets · delete off-screen        │
│  5. Collision detection (bullet ↔ ship)     │
│  6. Apply damage · update lives             │
│  7. Check win condition                     │
│  8. Render frame to ILI9486 display         │
│  9. Send game state to Pi B via SPI         │
│  10. Log metrics to RAM buffer → MicroSD    │
└─────────────────────────────────────────────┘
```

### SPI Packet Structure (9 Bytes)

```
┌────────┬────────┬───────┬────────┬───────┬─────┬──────┬──────┬──────────┐
│ Byte 0 │ Byte 1 │ Byte2 │ Byte 3 │ Byte4 │  5  │  6   │  7   │  Byte 8  │
├────────┼────────┼───────┼────────┼───────┼─────┼──────┼──────┼──────────┤
│  0xFF  │  X_H   │  X_L  │  Y_H   │  Y_L  │ BTN │ 0x00 │ 0x00 │ CHECKSUM │
│ Header │    X axis (16-bit)      │  Y axis (16-bit)    │ Res. │ XOR sum  │
└────────┴─────────────────────────┴────────────────────┴──────┴──────────┘

Checksum = X_H XOR X_L XOR Y_H XOR Y_L XOR BTN
```

---

## 📁 Project Structure

```
space-shooter-spi/
│
├── 📁 game/
│   ├── 📁 master/
│   │   └── master.py          # Pi A — game engine, display, P1 input
│   ├── 📁 slave/
│   │   └── slave.py           # Pi B — P2 input processor
│   └── 📁 game_logic/
│       └── claude.md          # Architecture reference document
│
├── 📁 circuit diagram/
│   └── circuit_diagram.png    # KiCad schematic export
│
├── 📁 document/
│   └── [SS_26][A06]_...pdf    # Full project documentation
│
├── 📁 logs/
│   └── .gitkeep               # game_log.csv written here at runtime
│
├── README.md
└── .gitignore
```

---

## 🚀 Getting Started

### Prerequisites

Both Raspberry Pis must have the following installed:

```bash
sudo apt update
sudo apt install python3 python3-pip
pip3 install spidev RPi.GPIO smbus2
```

Enable SPI on both Pis:

```bash
sudo raspi-config
# Interface Options → SPI → Enable
```

### Running the Game

**On Pi B (Slave) — start first:**
```bash
python3 slave.py
```

**On Pi A (Master) — start second:**
```bash
python3 master.py
```

Pi A will show the main menu. Press **Host Multiplayer Game**, wait for Pi B to connect, enter player names, and start the game.

---

## 📊 Data Logging

During gameplay, the following metrics are logged every frame to `logs/game_log.csv`:

| Column | Description |
|---|---|
| `timestamp` | HH:MM:SS:ms |
| `fps` | Frames per second |
| `cpu_temp` | CPU temperature (°C) |
| `spi_latency` | Round-trip SPI latency (ms) |
| `p1_lives` | Player 1 remaining lives |
| `p2_lives` | Player 2 remaining lives |
| `error` | Error code or "None" |

> Logs are buffered in RAM (60-row batches) and flushed to MicroSD only when the buffer is full or the game ends — ensuring zero impact on the 30 FPS loop.

---

## ⚙️ Technical Requirements

| Requirement | Target | Priority |
|---|---|---|
| Frame loop time | ≤ 33.3 ms | Critical |
| SPI clock frequency | 1 MHz ±5% | High |
| Input poll rate | ≥ 100 Hz | Medium |
| GPIO voltage | 0–3.3V | Critical |
| Power supply | 5V / ≥3A per node | High |
| CPU temperature | < 80°C under load | High |
| Ground resistance | ≤ 0.5 Ω between nodes | High |

---

## 👥 Team

| Student | ID | Contributions |
|---|---|---|
| Seifeldin Haggag | 22400909 | Project Plan · HW Architecture · Requirements |
| Berke Aksakal | 22514163 | State of the Art · HW Architecture · Circuit Diagram |
| Tarandeep Dhillon | 22407483 | SW Architecture · Circuit Diagram |
| Harun Dolcan | 22511850 | SW Architecture · Requirements |

---

## 📚 References

1. Motorola, Inc. (2003). *SPI Block Guide V03.06.* — [Source](https://www.nxp.com/docs/en/reference-manual/S12SPIV3.pdf)
2. Mitěv, M., & Pohl, L. (2022). *Kernel latency analysis on Raspberry Pi OS.* Brno University of Technology — [Source](https://dspace.vut.cz/bitstreams/19b5a46d-b7eb-4346-bacd-e596538d6e72/download)

---

## 📄 License

This project was developed as part of an academic course at **Technische Hochschule Deggendorf (THD)**, Campus Cham.  
Released under the [MIT License](LICENSE).

---

<div align="center">

**THD · NuW · Artificial Intelligence for Smart Sensors and Actuators · MSS-11**  
*Case Study Edge Device Architecture · Prof. Dr. Matthias Górka · v1.1*

</div>

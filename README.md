<div align="center">

# 🚀 Space Shooter via SPI

<img width="120" alt="THD Logo" src="assets/thd_logo.png" />

**A distributed real-time multiplayer game running on two Raspberry Pi 1 Model B+ nodes**  
**communicating over a hardware SPI bus at 1 MHz.**

![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-1%20Model%20B+-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white)
![SPI](https://img.shields.io/badge/Protocol-SPI%201MHz-brightgreen?style=flat-square)
![FPS](https://img.shields.io/badge/Target-30%20FPS-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

> **THD Campus Cham** · Faculty of Applied Natural Sciences and Industrial Engineering  
> Course: *Case Study Edge Device Architecture* · Semester: 26_SS · Group: A06

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
- 🖥️ **Real ILI9486 Display Driver** — full SPI-driven 480×320 rendering with ships, bullets, and HUD
- 🔒 **Data Integrity** — 8-bit XOR checksum on every 9-byte SPI packet
- 🛡️ **Dead Reckoning** — automatic motion estimation if the SPI link is interrupted for more than 2 frames
- 📊 **Live Data Logging** — CPU temperature, FPS, SPI latency, and game events logged to CSV on MicroSD
- 🕹️ **30 FPS Deterministic Loop** — fixed 33.3 ms execution window, every frame
- 🎯 **Dual-Button Start** — press both joystick buttons simultaneously to host the game

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
| 3.5" ILI9486 Resistive Touchscreen | 1 | Connected to Pi A via SPI0 CE1 |
| Analog Joystick Module (ADS1x15 ADC) | 2 | 3.3V, read via I2C — address 0x48 |
| MicroSD Card | 2 | OS + game assets + logs |
| USB Power Supply 5V/3A | 2 | One per Pi |
| Jumper Wires | — | SPI bus + common GND |

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

### LCD Wiring — ILI9486 → Pi A

```
LCD Pin 19 (LCD_SL/TP_SI)  → Pi A Pin 19 (GPIO10 / MOSI0)
LCD Pin 23 (LCD_SCK/TP_SCK) → Pi A Pin 23 (GPIO11 / SCLK0)
LCD Pin 18 (LCD_RS)         → Pi A Pin 18 (GPIO24)
LCD Pin 22 (RST)            → Pi A Pin 22 (GPIO25)
LCD Pin 24 (LCD_CS)         → Pi A Pin 26 (GPIO7  / CE1)
LCD Pin 1  (3.3V)           → Pi A Pin 1  (3.3V)
LCD Pin 2  (5V)             → Pi A Pin 2  (5V)
LCD Pin 15 (GND)            → GND
```

> LCD and Pi B share SPI0 — separated by Chip Select: **LCD = CE1 (GPIO7)**, **Pi B = CE0 (GPIO8)**

### Controller Pin Mapping

| Controller Pin | GPIO | Pi Pin | Function |
|---|---|---|---|
| I2C_SDA (ADC) | GPIO2 | Pin 3 | Joystick X/Y data |
| I2C_SCL (ADC) | GPIO3 | Pin 5 | Joystick X/Y clock |
| Joystick B7 | GPIO5 | Pin 29 | **Shoot** / Host trigger |
| Joystick BB | GPIO6 | Pin 31 | **Start** trigger |
| B1 Green | GPIO12 | Pin 32 | Menu / Confirm |
| B2 Pink | GPIO13 | Pin 33 | Button 2 |
| B3 White | GPIO19 | Pin 35 | Button 3 |
| B4 Yellow | GPIO16 | Pin 36 | Button 4 |
| B5 Blue | GPIO26 | Pin 37 | Button 5 |
| B6 Red | GPIO20 | Pin 38 | Button 6 |

> Same mapping applies to both Controller 1 (→ Pi A) and Controller 2 (→ Pi B).

> ⚠️ **Critical:** All GPIO signals operate at **3.3V**. Never connect 5V to any GPIO pin.

### Circuit Diagram

<img width="1755" height="1240" alt="circuit_diagram" src="https://github.com/user-attachments/assets/25cc8691-bea6-48bf-a340-a38c53c6a22a" />

---

## 🎮 How to Start the Game

```
1. Connect hardware per wiring tables above
2. Start Pi B first:   python3 slave.py
3. Start Pi A second:  python3 master.py
4. Pi A shows main menu on LCD
5. Press BOTH joystick buttons simultaneously (B7 + BB)
6. Wait for "P2 CONNECTED" screen
7. Countdown 3...2...1 — game begins!
```

---

## 🎮 Game Loop — How It Works

Every **33.3 ms** (30 FPS), the Master Pi executes the following sequence:

```
┌─────────────────────────────────────────────┐
│              MASTER GAME LOOP               │
│                 (33.3 ms)                   │
├─────────────────────────────────────────────┤
│  1. Read P1 joystick (X, Y, Shoot)          │
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
│ Header │    X axis (16-bit)      │   Y axis (16-bit)   │ Res. │ XOR sum  │
└────────┴─────────────────────────┴─────────────────────┴──────┴──────────┘
Checksum = X_H XOR X_L XOR Y_H XOR Y_L XOR BTN
```

---

## 📁 Project Structure

```
space-shooter-spi/
│
├── 📁 game/
│   ├── 📁 master/
│   │   └── master.py          # Pi A — game engine, ILI9486 driver, P1 input
│   ├── 📁 slave/
│   │   └── slave.py           # Pi B — P2 input processor, SPI response
│   └── 📁 game_logic/
│       └── claude.md          # Architecture reference document
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
sudo apt install python3 python3-pip i2c-tools
pip3 install spidev RPi.GPIO smbus2
```

Enable SPI and I2C on both Pis:

```bash
sudo raspi-config
# Interface Options → SPI → Enable
# Interface Options → I2C → Enable
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

**To start hosting:** press **both joystick buttons (B7 + BB) at the same time** on Pi A.

---

## 📊 Data Logging

During gameplay, the following metrics are logged every frame to `logs/game_log.csv`:

| Column | Description |
|---|---|
| `timestamp` | HH:MM:SS |
| `fps` | Frames per second |
| `cpu_temp` | CPU temperature (°C) |
| `spi_latency_ms` | Round-trip SPI latency (ms) |
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
| ADC resolution | 16-bit (65,536 steps) | High |

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

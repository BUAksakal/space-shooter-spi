.# claude.md — Space Shooter via SPI

## Project Context
THD Case Study Edge Device Architecture — Group A06.
2-player Space Shooter game. Two Raspberry Pi 1 nodes communicating via SPI protocol.
Submission deadline: 30 June 2026.

---

## Hardware

### Pi A — Master Node
- Model: Raspberry Pi 1
- SoC: BCM2835 (ARMv6, 700MHz, single core)
- RAM: 256MB or 512MB
- Role: Game engine + display + P1 joystick
- Display: 3.5" ILI9486 resistive touchscreen (via SPI0 CE1)
- Storage: MicroSD (OS + game_log.csv)
- GPIO: 3.3V logic — 5V STRICTLY FORBIDDEN
- Power: 5V / min 3A USB

### Pi B — Slave Node
- Model: Raspberry Pi 1
- SoC: BCM2835 (ARMv6, 700MHz, single core)
- RAM: 256MB or 512MB
- Role: P2 joystick reading and forwarding only
- Display: NONE
- Storage: MicroSD (OS only)
- GPIO: 3.3V logic — 5V STRICTLY FORBIDDEN
- Power: 5V / min 3A USB

### SPI Connection
- SPI0: Pi A ↔ Pi B (1 MHz, CE0)
- Display: SPI0 CE1 or bit-banging
- Lines: SCLK, MOSI, MISO, CE0
- GND: Common reference — both Pi GND pins must be connected
- Voltage: 3.3V — NO level shifter needed

### Controllers
- 2x joystick (3.3V)
- Axis resolution: 16-bit (65,536 steps)
- Reading: I2C ADC
- Poll rate: min 100Hz

---

## File Structure

```
space-shooter-spi/
├── master/
│   └── master.py        → runs on Pi A
├── slave/
│   └── slave.py         → runs on Pi B
├── docs/
├── logs/
│   └── .gitkeep
├── claude.md
└── README.md
```

---

## Module Flows

### Module Interconnection
```
Module 1 (Pi A Startup)
    └── calls game_loop()
            └── Module 3 (Game Loop) — every frame
                    ├── Module 4 (SPI Master) — get data from Pi B
                    │       └── Module 5 (SPI Slave Pi B) — responds
                    └── Module 6 (Data Logger) — end of every frame

Module 2 (Pi B Startup)
    └── starts spi_slave()
            └── Module 5 (SPI Slave) — background thread
```

---

### Module 1 — Pi A Startup & Join
**File:** master.py → startup()
**Entry:** Program start
**Exit:** calls game_loop()

```
1.  Initialize Pi A (Screen, SPI, GPIO, Buttons)
2.  Show Main Menu on screen
3.  "Host Multiplayer Game" pressed? → NO: wait
4.  Show "Waiting for Player 2" screen
5.  Send JOIN_REQUEST to Pi B via SPI
6.  JOIN_ACK received from Pi B? → NO: wait (loop)
7.  Show "Player 2 Connected"
8.  Prompt Player 1 to enter name (on Pi A screen)
9.  Prompt Player 2 to enter name (on Pi A screen)
10. Display both names and Play button
11. Countdown 3...2...1
12. Call game_loop()
```

---

### Module 2 — Pi B Startup & Join
**File:** slave.py → startup()
**Entry:** Program start
**Exit:** calls spi_slave()

```
1. Initialize Pi B (SPI Slave, GPIO, Joystick, Buttons)
2. Wait silently on SPI line — no screen, no action
3. JOIN_REQUEST received from Pi A? → NO: wait (loop)
4. Send JOIN_ACK signal to Pi A via SPI
5. Wait for game to start
6. SPI data received from Pi A? → NO: wait (loop)
7. Call spi_slave()
```

---

### Module 3 — Game Loop (Pi A Main Thread)
**File:** master.py → game_loop()
**Entry:** end of startup() in Module 1
**Exit:** Game Over → game over screen
**Timing:** 33.3ms (30 FPS) — this window MUST NOT be exceeded

```
LOOP (until game over):
    1.  Read Pi A joystick (X, Y, Shoot, Menu)
    2.  Get Pi B data via SPI Slave (X, Y, Buttons) → Module 4
    3.  Update ship positions + apply boundary rules
    4.  Update bullets (move, delete off-screen, add new if fire)
    5.  Collision check (bullet ↔ ship)
    6.  Apply hit result (update lives)
    7.  Check win condition
    8.  Game over? → YES: go to End
    9.  Render (background, ships, bullets, lives)
    10. Send game state to Pi B (lives, score, game state)
    11. Call data_logger() → Module 6
    12. If 33.3ms not elapsed: wait → go back to start

Game Over:
    - Show game over screen
    - Send game over signal to Pi B
    - Flush data logger
```

---

### Module 4 — SPI Master (Pi A Background Thread)
**File:** master.py → spi_master()
**Entry:** called by game_loop() every frame
**Exit:** returns Pi B X, Y, BTN data to game_loop

```
1.  Set CE0 LOW (start SPI transaction)
2.  Send request to Pi B ("give me your data")
3.  Wait for response until timeout
    → Timeout: ask for resend
4.  Packet received?
    → NO: wait again
5.  Check header (is it 0xFF?)
    → Invalid: discard packet, use last valid state
6.  Validate checksum (X XOR Y XOR BTN == CS?)
    → Invalid: discard packet, use last valid state
7.  Extract X, Y, BTN values from packet
8.  Send game state to Pi B (lives, score, game state, winner)
9.  Set CE0 HIGH (end SPI transaction)
10. Return Pi B input data to game_loop
```

---

### Module 5 — SPI Slave (Pi B Background Thread)
**File:** slave.py → spi_slave()
**Entry:** end of startup() in Module 2
**Exit:** stops when game over signal received

```
LOOP (until game over):
    1. Wait for CE0 LOW (Pi A starts transaction)
    2. Request received from Pi A? → NO: keep waiting
    3. Read joystick X, Y (GPIO/I2C)
    4. Read Shoot button state
    5. Build SPI packet:
       [0xFF][X_H][X_L][Y_H][Y_L][BTN][0x00][0x00][CHECKSUM]
       Checksum = X_H XOR X_L XOR Y_H XOR Y_L XOR BTN
    6. Send packet to Pi A via MISO line
    7. Wait for game state response from Pi A
    8. Receive game state (lives, score, winner, game state)
    9. Game over signal received?
       → YES: CE0 HIGH, End
       → NO: go back to start
```

---

### Module 6 — Data Logger
**File:** master.py → data_logger()
**Entry:** called by game_loop() at end of every frame
**Exit:** game_log.csv saved to MicroSD

```
1. Read system metrics:
   - CPU temperature (°C)
   - Current FPS
   - SPI latency (ms)
   - P1 lives, P2 lives
   - Timestamp (HH:MM:SS:ms)
2. Any errors this frame?
   → YES: append error code to row
   → NO: error = "None"
3. Build CSV row:
   [timestamp, fps, cpu_temp, spi_latency, p1_lives, p2_lives, error]
4. Add row to RAM buffer
5. Buffer full? (60 rows)
   → YES: write to MicroSD (append to game_log.csv), clear buffer
   → NO: continue
6. Game over?
   → YES: flush remaining buffer, safely close file
   → NO: return to game_loop
```

---

## SPI Packet Structure (9 Bytes)

### Pi B → Pi A (input packet)
```
Byte 0: 0xFF          → Header (packet start marker)
Byte 1: X_HIGH        → X axis high byte
Byte 2: X_LOW         → X axis low byte
Byte 3: Y_HIGH        → Y axis high byte
Byte 4: Y_LOW         → Y axis low byte
Byte 5: BTN           → Button state (Shoot etc.)
Byte 6: 0x00          → Reserved
Byte 7: 0x00          → Reserved
Byte 8: CHECKSUM      → X_H XOR X_L XOR Y_H XOR Y_L XOR BTN
```

### Pi A → Pi B (game state packet)
```
Content: lives, score, game_state, winner
Checksum: same XOR logic
```

### Checksum Rule
```
Sending:   checksum = XOR of all data bytes
Receiving: recalculate → does it match?
           YES: use packet
           NO:  discard packet, use last valid state (Dead Reckoning)
```

---

## Pi 1 Constraints — MUST BE RESPECTED AT ALL TIMES

```
1. ARMv6, 700MHz, SINGLE core
   → No heavy computation
   → No unnecessary loops
   → Keep everything simple and lightweight

2. RAM: 256MB
   → No large lists
   → No unnecessary object creation
   → Buffer max 60 rows

3. SPI: Only SPI0 available (hardware)
   → Pi A ↔ Pi B: SPI0 CE0
   → Display: SPI0 CE1 or bit-banging

4. GPIO: 3.3V
   → 5V STRICTLY FORBIDDEN
   → No level shifter needed (Pi 1 ↔ Pi 1)

5. Timing: 33.3ms window
   → Entire game loop must complete within this window
   → Display render is the heaviest operation — must be optimized
```

---

## Coding Rules

```
1. ONLY the logic defined in the flowcharts is implemented
   → No extra features
   → Nothing added that is not in the documentation

2. Each module is written as a separate function
   → startup(), game_loop(), spi_master(),
      spi_slave(), data_logger()

3. Only two files exist: master.py and slave.py
   → No additional files

4. All modules must be consistent with each other
   → SPI packet structure identical on both sides
   → Timing respected across all modules

5. Error handling:
   → Corrupted packet: use last valid state
   → SPI interruption >2 frames: Dead Reckoning
   → Storage missing: non-fatal warning, game continues
```

---

## Python Libraries

```
master.py:
  - RPi.GPIO     → GPIO control
  - spidev       → SPI communication
  - smbus        → I2C (joystick ADC)
  - framebuffer  → display (pygame may be too heavy on Pi 1)
  - time         → timing (33.3ms loop)
  - csv          → data logger

slave.py:
  - RPi.GPIO     → GPIO control
  - spidev       → SPI slave
  - smbus        → I2C (joystick ADC)
  - time         → timing
  - threading    → background thread
```

---

## Game Variables

```python
# Game state
p1_lives = 3
p2_lives = 3
p1_score = 0
p2_score = 0
game_state = "playing"  # "playing", "game_over"
winner = None

# Positions
p1_x, p1_y = 0, 0
p2_x, p2_y = 0, 0

# Bullets
bullets = []  # [x, y, owner, direction]

# Timing
FRAME_TIME = 0.0333  # 33.3ms
```

---

*This file is provided to Claude at the start of every coding session.*
*Only the logic defined in this document is implemented. Nothing extra is added.*

#!/usr/bin/env python3
# =============================================================================
# master.py — Pi A (Master Node)
# Space Shooter via SPI — THD Case Study A06
# Runs on: Raspberry Pi 1, BCM2835, ARMv6, 700MHz
# Role: Game engine + display + P1 joystick + SPI Master + Data Logger
# =============================================================================

import RPi.GPIO as GPIO
import spidev
import smbus
import time
import csv
import os

# =============================================================================
# HARDWARE CONSTANTS
# =============================================================================

# SPI
SPI_BUS        = 0
SPI_DEVICE_PB  = 0        # CE0 → Pi B
SPI_DEVICE_LCD = 1        # CE1 → ILI9486 display
SPI_SPEED_HZ   = 1_000_000

# I2C (Joystick ADC)
I2C_BUS        = 1
ADC_ADDR       = 0x48     # ADS1x15 default address
ADC_X_CH       = 0        # X axis channel
ADC_Y_CH       = 1        # Y axis channel

# GPIO
GPIO_SHOOT_P1  = 17       # P1 shoot button
GPIO_MENU      = 27       # Menu button
GPIO_LCD_DC    = 24       # LCD Data/Command
GPIO_LCD_RST   = 25       # LCD Reset

# Display (ILI9486 — 3.5", 480x320)
LCD_WIDTH      = 480
LCD_HEIGHT     = 320

# Timing
FRAME_TIME     = 0.0333   # 33.3 ms → 30 FPS
SPI_TIMEOUT    = 0.005    # 5 ms SPI response timeout

# SPI Packet
PKT_SIZE       = 9
PKT_HEADER     = 0xFF
DEAD_RECKONING_LIMIT = 2  # frames before dead reckoning

# Game
MAX_LIVES      = 3
BULLET_SPEED   = 8
SHIP_SPEED     = 4
SHIP_W         = 20
SHIP_H         = 20
BULLET_W       = 4
BULLET_H       = 8

# Data Logger
LOG_PATH       = "/home/pi/logs/game_log.csv"
LOG_BUFFER_MAX = 60

# =============================================================================
# GAME VARIABLES
# =============================================================================

p1_lives = MAX_LIVES
p2_lives = MAX_LIVES
p1_score = 0
p2_score = 0
game_state = "playing"    # "playing", "game_over"
winner = None

p1_x, p1_y = LCD_WIDTH // 4, LCD_HEIGHT // 2
p2_x, p2_y = (LCD_WIDTH * 3) // 4, LCD_HEIGHT // 2

bullets = []              # [x, y, owner, direction]  direction: 1=right, -1=left

FRAME_TIME = 0.0333

# =============================================================================
# GLOBAL OBJECTS
# =============================================================================

spi   = None
bus   = None
p2_last_x   = 32767      # mid-range (16-bit center)
p2_last_y   = 32767
p2_last_btn = 0
spi_miss_frames = 0

log_buffer = []
log_file_handle = None

p1_name = "Player1"
p2_name = "Player2"

# =============================================================================
# MODULE 1 — Pi A STARTUP & JOIN
# =============================================================================

def startup():
    """
    Module 1: Initialize hardware, show menu, connect to Pi B, start game loop.
    Flowchart steps 1-12.
    """
    global spi, bus, log_file_handle

    # --- Step 1: Initialize Pi A ---
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(GPIO_SHOOT_P1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(GPIO_MENU,     GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(GPIO_LCD_DC,   GPIO.OUT)
    GPIO.setup(GPIO_LCD_RST,  GPIO.OUT)

    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE_PB)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0

    try:
        bus = smbus.SMBus(I2C_BUS)
    except Exception:
        bus = None  # ADC not connected — fallback to center

    lcd_init()

    # Data logger: ensure log directory exists
    log_dir = os.path.dirname(LOG_PATH)
    try:
        os.makedirs(log_dir, exist_ok=True)
        write_header = not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0
        log_file_handle = open(LOG_PATH, "a", newline="")
        if write_header:
            writer = csv.writer(log_file_handle)
            writer.writerow(["timestamp", "fps", "cpu_temp", "spi_latency_ms",
                             "p1_lives", "p2_lives", "error"])
            log_file_handle.flush()
    except OSError:
        # Non-fatal: storage missing — game continues
        log_file_handle = None
        print("[WARN] Storage not available — data logging disabled.")

    # --- Step 2: Show Main Menu ---
    lcd_draw_main_menu()

    # --- Step 3: Wait for "Host Multiplayer Game" ---
    while True:
        if not GPIO.input(GPIO_MENU):   # button pressed (active low)
            time.sleep(0.05)            # debounce
            break
        time.sleep(0.01)

    # --- Step 4: Show "Waiting for Player 2" ---
    lcd_draw_text("Waiting for Player 2...")

    # --- Steps 5-6: Send JOIN_REQUEST, wait for JOIN_ACK ---
    while True:
        _spi_send_byte(0xA1)            # JOIN_REQUEST opcode
        time.sleep(0.1)
        resp = _spi_recv_byte()
        if resp == 0xA2:                # JOIN_ACK
            break
        time.sleep(0.1)

    # --- Step 7: Show "Player 2 Connected" ---
    lcd_draw_text("Player 2 Connected!")
    time.sleep(1)

    # --- Steps 8-9: Enter names (simple selection on Pi A screen) ---
    global p1_name, p2_name
    p1_name = "Player1"   # On real hardware: on-screen keyboard input
    p2_name = "Player2"

    # --- Step 10: Display both names & Play button ---
    lcd_draw_text(f"P1: {p1_name}  P2: {p2_name}\nPress MENU to Play")

    # Wait for play button
    while GPIO.input(GPIO_MENU):
        time.sleep(0.01)
    time.sleep(0.05)

    # --- Step 11: Countdown 3...2...1 ---
    for n in [3, 2, 1]:
        lcd_draw_text(str(n))
        time.sleep(1)

    # --- Step 12: Enter game loop ---
    game_loop()


# =============================================================================
# MODULE 3 — GAME LOOP (Pi A Main Thread)
# =============================================================================

def game_loop():
    """
    Module 3: Main game loop running at 30 FPS (33.3 ms per frame).
    """
    global p1_lives, p2_lives, p1_score, p2_score
    global p1_x, p1_y, p2_x, p2_y
    global bullets, game_state, winner

    frame_error = "None"

    while game_state == "playing":
        frame_start = time.time()
        frame_error = "None"

        # --- Step 1: Read Pi A joystick (P1) ---
        p1_jx, p1_jy, p1_shoot = _read_joystick_p1()

        # --- Step 2: Get Pi B data via SPI Master ---
        spi_start = time.time()
        p2_jx, p2_jy, p2_btn, spi_ok = spi_master()
        spi_latency = (time.time() - spi_start) * 1000  # ms

        if not spi_ok:
            frame_error = "SPI_ERR"

        # --- Step 3: Update ship positions + boundary rules ---
        # P1 moves: joystick X → horizontal, joystick Y → vertical
        # 16-bit center = 32767; normalize to -1.0 … +1.0
        p1_dx = _normalize_axis(p1_jx)
        p1_dy = _normalize_axis(p1_jy)
        p1_x = _clamp(int(p1_x + p1_dx * SHIP_SPEED), SHIP_W, LCD_WIDTH  // 2 - SHIP_W)
        p1_y = _clamp(int(p1_y + p1_dy * SHIP_SPEED), SHIP_H, LCD_HEIGHT - SHIP_H)

        p2_dx = _normalize_axis(p2_jx)
        p2_dy = _normalize_axis(p2_jy)
        p2_x = _clamp(int(p2_x + p2_dx * SHIP_SPEED), LCD_WIDTH // 2 + SHIP_W, LCD_WIDTH  - SHIP_W)
        p2_y = _clamp(int(p2_y + p2_dy * SHIP_SPEED), SHIP_H,                   LCD_HEIGHT - SHIP_H)

        # --- Step 4: Update bullets ---
        # Add new bullet if shoot pressed
        if p1_shoot:
            bullets.append([p1_x + SHIP_W, p1_y + SHIP_H // 2, 1,  1])  # P1 shoots right
        if p2_btn & 0x01:
            bullets.append([p2_x,          p2_y + SHIP_H // 2, 2, -1])  # P2 shoots left

        # Move bullets, remove off-screen
        remaining = []
        for b in bullets:
            b[0] += b[3] * BULLET_SPEED
            if 0 <= b[0] <= LCD_WIDTH:
                remaining.append(b)
        bullets = remaining

        # --- Step 5-6: Collision check + apply hit ---
        new_bullets = []
        for b in bullets:
            hit = False
            if b[2] == 1:  # P1 bullet → check P2 ship
                if _rect_overlap(b[0], b[1], BULLET_W, BULLET_H,
                                 p2_x, p2_y, SHIP_W, SHIP_H):
                    p2_lives -= 1
                    p1_score += 1
                    hit = True
            else:          # P2 bullet → check P1 ship
                if _rect_overlap(b[0], b[1], BULLET_W, BULLET_H,
                                 p1_x, p1_y, SHIP_W, SHIP_H):
                    p1_lives -= 1
                    p2_score += 1
                    hit = True
            if not hit:
                new_bullets.append(b)
        bullets = new_bullets

        # --- Step 7: Check win condition ---
        if p1_lives <= 0:
            winner = p2_name
            game_state = "game_over"
        elif p2_lives <= 0:
            winner = p1_name
            game_state = "game_over"

        # --- Step 8: Game over check ---
        if game_state == "game_over":
            break

        # --- Step 9: Render frame ---
        lcd_render(p1_x, p1_y, p2_x, p2_y, bullets,
                   p1_lives, p2_lives, p1_score, p2_score)

        # --- Step 10: Game state already sent inside spi_master() (Module 4 Step 8) ---

        # --- Step 11: Data logger ---
        fps_actual = 1.0 / max(time.time() - frame_start, 0.001)
        data_logger(fps_actual, spi_latency, frame_error)

        # --- Step 12: Frame timing — wait remainder of 33.3 ms ---
        elapsed = time.time() - frame_start
        remaining_time = FRAME_TIME - elapsed
        if remaining_time > 0:
            time.sleep(remaining_time)

    # --- Game Over ---
    lcd_draw_text(f"GAME OVER\nWinner: {winner}\n{p1_name}: {p1_score}  {p2_name}: {p2_score}")
    _spi_send_byte(0xEE)   # Game over signal to Pi B
    data_logger_flush()
    time.sleep(5)
    GPIO.cleanup()


# =============================================================================
# MODULE 4 — SPI MASTER (Pi A → Pi B communication)
# =============================================================================

def spi_master():
    """
    Module 4: Request joystick data from Pi B via SPI.
    Returns: (x, y, btn, ok)  — ok=False means dead reckoning applied.
    """
    global p2_last_x, p2_last_y, p2_last_btn, spi_miss_frames

    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES):
        try:
            # --- Step 1: CE0 LOW (handled by spidev automatically on transfer) ---
            # --- Step 2: Send request to Pi B ---
            request = [0xAA, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

            # --- Step 3-4: Transfer; spidev is full-duplex ---
            deadline = time.time() + SPI_TIMEOUT
            response = spi.xfer2(request, SPI_SPEED_HZ, 0)
            if time.time() > deadline:
                # Timeout — ask for resend (Step 3: retry)
                continue

            # --- Step 5: Check header ---
            if response[0] != PKT_HEADER:
                continue   # invalid header → retry

            # --- Step 6: Validate checksum ---
            x_h  = response[1]
            x_l  = response[2]
            y_h  = response[3]
            y_l  = response[4]
            btn  = response[5]
            cs   = response[8]
            calc = x_h ^ x_l ^ y_h ^ y_l ^ btn

            if calc != cs:
                continue   # bad checksum → retry

            # --- Step 7: Extract values ---
            x_val = (x_h << 8) | x_l
            y_val = (y_h << 8) | y_l

            # --- Step 8: Send game state back ---
            _send_game_state_to_pb()

            # --- Step 9: CE0 HIGH — handled by spidev ---

            # Valid packet — update last known state
            p2_last_x   = x_val
            p2_last_y   = y_val
            p2_last_btn = btn
            spi_miss_frames = 0

            return x_val, y_val, btn, True

        except Exception:
            continue

    # All retries exhausted → dead reckoning
    spi_miss_frames += 1
    return _dead_reckon()


def _dead_reckon():
    """
    Return last valid state when SPI fails.
    If miss > DEAD_RECKONING_LIMIT: hold position (zero delta).
    """
    if spi_miss_frames > DEAD_RECKONING_LIMIT:
        return 32767, 32767, 0, False   # center — no movement
    return p2_last_x, p2_last_y, p2_last_btn, False


def _send_game_state_to_pb():
    """Send game state packet (lives, score, game_state, winner) to Pi B."""
    winner_byte = 0x01 if winner == p1_name else (0x02 if winner == p2_name else 0x00)
    state_byte  = 0xEE if game_state == "game_over" else 0x01

    data = [
        state_byte,
        p1_lives & 0xFF,
        p2_lives & 0xFF,
        (p1_score >> 8) & 0xFF,
        p1_score & 0xFF,
        (p2_score >> 8) & 0xFF,
        p2_score & 0xFF,
        winner_byte,
        0x00   # checksum placeholder
    ]
    cs = 0
    for b in data[:-1]:
        cs ^= b
    data[8] = cs

    try:
        spi.xfer2(data, SPI_SPEED_HZ, 0)
    except Exception:
        pass


# =============================================================================
# MODULE 6 — DATA LOGGER
# =============================================================================

def data_logger(fps, spi_latency_ms, error="None"):
    """
    Module 6: Log frame metrics to RAM buffer; flush to CSV every 60 rows.
    """
    global log_buffer

    ts  = time.strftime("%H:%M:%S") + f":{int((time.time() % 1) * 1000):03d}"
    cpu = _read_cpu_temp()

    row = [ts, f"{fps:.1f}", f"{cpu:.1f}", f"{spi_latency_ms:.2f}",
           p1_lives, p2_lives, error]

    log_buffer.append(row)

    # --- Flush when buffer full (60 rows) ---
    if len(log_buffer) >= LOG_BUFFER_MAX:
        _flush_log_buffer()


def data_logger_flush():
    """Flush remaining buffer at game over."""
    _flush_log_buffer()
    if log_file_handle:
        try:
            log_file_handle.close()
        except Exception:
            pass


def _flush_log_buffer():
    global log_buffer
    if not log_file_handle or not log_buffer:
        return
    try:
        writer = csv.writer(log_file_handle)
        writer.writerows(log_buffer)
        log_file_handle.flush()
        log_buffer = []
    except OSError:
        # Non-fatal: storage missing
        print("[WARN] Log flush failed — storage unavailable.")
        log_buffer = []


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _read_joystick_p1():
    """Read P1 joystick from I2C ADC (ADS1x15) and shoot button from GPIO."""
    x, y = 32767, 32767   # default center
    if bus:
        try:
            # ADS1x15: write config, read result (simplified)
            bus.write_byte_data(ADC_ADDR, 0x01, 0xC3)  # CH0, single-shot
            time.sleep(0.001)
            raw = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
            x = ((raw[0] << 8) | raw[1]) & 0xFFFF

            bus.write_byte_data(ADC_ADDR, 0x01, 0xD3)  # CH1
            time.sleep(0.001)
            raw = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
            y = ((raw[0] << 8) | raw[1]) & 0xFFFF
        except Exception:
            pass

    shoot = not GPIO.input(GPIO_SHOOT_P1)   # active low
    return x, y, shoot


def _normalize_axis(raw_16bit):
    """Normalize 16-bit ADC value (0-65535) to -1.0 … +1.0."""
    center = 32767
    dead_zone = 2000
    delta = raw_16bit - center
    if abs(delta) < dead_zone:
        return 0.0
    if delta > 0:
        return (delta - dead_zone) / (center - dead_zone)
    return (delta + dead_zone) / (center - dead_zone)


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _rect_overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return (ax < bx + bw and ax + aw > bx and
            ay < by + bh and ay + ah > by)


def _read_cpu_temp():
    """Read BCM2835 CPU temperature from sysfs."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return 0.0


def _spi_send_byte(byte):
    try:
        spi.xfer2([byte], SPI_SPEED_HZ, 0)
    except Exception:
        pass


def _spi_recv_byte():
    try:
        resp = spi.xfer2([0x00], SPI_SPEED_HZ, 0)
        return resp[0]
    except Exception:
        return 0x00


# =============================================================================
# LCD STUB FUNCTIONS (ILI9486 — framebuffer / bit-bang)
# These wrap low-level display commands.
# Replace with actual ILI9486 driver calls for the real hardware.
# =============================================================================

def lcd_init():
    """Initialize ILI9486 display over SPI."""
    GPIO.output(GPIO_LCD_RST, GPIO.LOW)
    time.sleep(0.05)
    GPIO.output(GPIO_LCD_RST, GPIO.HIGH)
    time.sleep(0.05)
    # ILI9486 init sequence would be sent here via SPI CE1


def lcd_draw_main_menu():
    """Draw main menu — 'Host Multiplayer Game' button."""
    lcd_clear(0x0000)
    lcd_draw_text("Space Shooter\nPress MENU to Host")


def lcd_clear(color=0x0000):
    """Fill screen with color (16-bit RGB565)."""
    pass   # Implemented with ILI9486 fill command


def lcd_draw_text(text):
    """Draw text string on screen (top-left aligned)."""
    print(f"[LCD] {text}")   # Console fallback for dev/testing


def lcd_render(p1x, p1y, p2x, p2y, blist, p1l, p2l, p1s, p2s):
    """
    Render one game frame:
      - Clear background
      - Draw P1 ship, P2 ship
      - Draw all bullets
      - Draw HUD (lives, score)
    Optimized: draw only dirty regions to stay within 33.3 ms.
    """
    lcd_clear(0x0010)           # dark background

    # Ships (filled rectangles in player colors)
    _lcd_fill_rect(p1x, p1y, SHIP_W, SHIP_H, 0x07E0)   # P1 = green
    _lcd_fill_rect(p2x, p2y, SHIP_W, SHIP_H, 0xF800)   # P2 = red

    # Bullets
    for b in blist:
        color = 0x07FF if b[2] == 1 else 0xFFE0         # cyan / yellow
        _lcd_fill_rect(b[0], b[1], BULLET_W, BULLET_H, color)

    # HUD — top bar
    lcd_draw_text(f"{p1_name} ❤x{p1l} {p1s}pts  |  {p2_name} ❤x{p2l} {p2s}pts")


def _lcd_fill_rect(x, y, w, h, color):
    """Draw filled rectangle at (x,y) size (w×h) with RGB565 color."""
    pass   # Implemented with ILI9486 set_window + fill


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        startup()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        data_logger_flush()
        try:
            GPIO.cleanup()
        except Exception:
            pass
        if spi:
            spi.close()

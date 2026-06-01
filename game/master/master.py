#!/usr/bin/env python3
# =============================================================================
# master.py — Pi A (Master Node)
# Space Shooter via SPI — THD Case Study A06
# Pi 1 B+, BCM2835, ARMv6 700MHz, single core
# Role: Game engine + ILI9486 display + P1 input + SPI Master + Data Logger
# =============================================================================

import RPi.GPIO as GPIO
import spidev
import smbus
import time
import csv
import os
import struct

# =============================================================================
# HARDWARE CONSTANTS — matched to schematic
# =============================================================================

# SPI
SPI_BUS         = 0
SPI_DEV_SLAVE   = 0          # CE0 (GPIO8)  → Pi B
SPI_DEV_LCD     = 1          # CE1 (GPIO7)  → ILI9486
SPI_SPEED_HZ    = 1_000_000  # 1 MHz

# I2C
I2C_BUS         = 1          # GPIO2/GPIO3 → I2C-1 on Pi 1 B+
ADC_ADDR        = 0x48       # ADS1x15, ADDR pin → GND

# GPIO — Controller 1 (schematic verified)
GPIO_SHOOT      = 5          # Pin 29 — Joystick B7
GPIO_MENU       = 12         # Pin 32 — B1 Green  (Host / confirm)
GPIO_BTN_B2     = 13         # Pin 33 — B2 Pink
GPIO_BTN_B3     = 19         # Pin 35 — B3 White
GPIO_BTN_B4     = 16         # Pin 36 — B4 Yellow
GPIO_BTN_B5     = 26         # Pin 37 — B5 Blue
GPIO_BTN_B6     = 20         # Pin 38 — B6 Red
GPIO_JOY_BB     = 6          # Pin 31 — Joystick BB

# GPIO — LCD ILI9486
GPIO_LCD_DC     = 24         # Pin 18 — Data/Command
GPIO_LCD_RST    = 25         # Pin 22 — Reset

# Display
LCD_W           = 480
LCD_H           = 320

# Timing
FRAME_TIME      = 0.0333     # 33.3 ms = 30 FPS
SPI_TIMEOUT     = 0.005      # 5 ms

# SPI Packet
PKT_SIZE        = 9
PKT_HEADER      = 0xFF

# Game
MAX_LIVES       = 3
BULLET_SPEED    = 8
SHIP_SPEED      = 4
SHIP_W          = 20
SHIP_H          = 20
BULLET_W        = 4
BULLET_H        = 8
DEADZONE        = 2000       # 16-bit joystick deadzone

# Logger
LOG_PATH        = "/home/pi/logs/game_log.csv"
LOG_BUF_MAX     = 60

# Colors RGB565
C_BLACK   = 0x0000
C_WHITE   = 0xFFFF
C_GREEN   = 0x07E0
C_RED     = 0xF800
C_CYAN    = 0x07FF
C_YELLOW  = 0xFFE0
C_BLUE    = 0x001F
C_DARK    = 0x0010

# ILI9486 commands
ILI_NOP        = 0x00
ILI_SWRESET    = 0x01
ILI_SLPOUT     = 0x11
ILI_DISPON     = 0x29
ILI_CASET      = 0x2A
ILI_PASET      = 0x2B
ILI_RAMWR      = 0x2C
ILI_MADCTL     = 0x36
ILI_COLMOD     = 0x3A

# =============================================================================
# GAME STATE
# =============================================================================

p1_lives = MAX_LIVES
p2_lives = MAX_LIVES
p1_score = 0
p2_score = 0
game_state  = "playing"
winner      = None
p1_x = LCD_W // 4
p1_y = LCD_H // 2
p2_x = (LCD_W * 3) // 4
p2_y = LCD_H // 2
bullets     = []

# SPI dead-reckoning state
p2_last_x   = 32767
p2_last_y   = 32767
p2_last_btn = 0
spi_miss    = 0

# Logger
log_buffer  = []
log_fh      = None

p1_name = "P1"
p2_name = "P2"

# Globals
spi_obj  = None
spi_lcd  = None
bus      = None

# =============================================================================
# LCD DRIVER — ILI9486, SPI0 CE1
# =============================================================================

def _lcd_cmd(cmd):
    GPIO.output(GPIO_LCD_DC, GPIO.LOW)
    spi_lcd.xfer2([cmd])

def _lcd_data(data):
    GPIO.output(GPIO_LCD_DC, GPIO.HIGH)
    if isinstance(data, int):
        spi_lcd.xfer2([data])
    else:
        # send in 4096-byte chunks (Pi 1 SPI buffer limit)
        for i in range(0, len(data), 4096):
            spi_lcd.xfer2(data[i:i+4096])

def lcd_init():
    """Hard-reset and initialize ILI9486."""
    GPIO.output(GPIO_LCD_RST, GPIO.LOW)
    time.sleep(0.05)
    GPIO.output(GPIO_LCD_RST, GPIO.HIGH)
    time.sleep(0.12)

    _lcd_cmd(ILI_SWRESET); time.sleep(0.12)
    _lcd_cmd(ILI_SLPOUT);  time.sleep(0.12)

    # Pixel format: 16-bit RGB565
    _lcd_cmd(ILI_COLMOD); _lcd_data(0x55)

    # Memory access: landscape, BGR
    _lcd_cmd(ILI_MADCTL); _lcd_data(0x28)

    _lcd_cmd(ILI_DISPON)
    time.sleep(0.05)

def _lcd_set_window(x0, y0, x1, y1):
    _lcd_cmd(ILI_CASET)
    GPIO.output(GPIO_LCD_DC, GPIO.HIGH)
    spi_lcd.xfer2([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
    _lcd_cmd(ILI_PASET)
    GPIO.output(GPIO_LCD_DC, GPIO.HIGH)
    spi_lcd.xfer2([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
    _lcd_cmd(ILI_RAMWR)
    GPIO.output(GPIO_LCD_DC, GPIO.HIGH)

def lcd_fill(color):
    """Fill entire screen with one color."""
    hi = (color >> 8) & 0xFF
    lo = color & 0xFF
    _lcd_set_window(0, 0, LCD_W - 1, LCD_H - 1)
    chunk = [hi, lo] * 512   # 512 pixels per chunk
    total = LCD_W * LCD_H
    sent = 0
    while sent < total:
        n = min(512, total - sent)
        spi_lcd.xfer2([hi, lo] * n)
        sent += n

def lcd_rect(x, y, w, h, color):
    """Draw filled rectangle."""
    if x >= LCD_W or y >= LCD_H:
        return
    x1 = min(x + w - 1, LCD_W - 1)
    y1 = min(y + h - 1, LCD_H - 1)
    hi = (color >> 8) & 0xFF
    lo = color & 0xFF
    _lcd_set_window(x, y, x1, y1)
    n = (x1 - x + 1) * (y1 - y + 1)
    chunk_size = 256
    data = [hi, lo] * chunk_size
    sent = 0
    while sent < n:
        batch = min(chunk_size, n - sent)
        spi_lcd.xfer2([hi, lo] * batch)
        sent += batch

def lcd_char(x, y, ch, color, bg):
    """Draw one 5x7 character (no font lib needed on Pi 1)."""
    # Minimal 5x7 font for digits, letters, common symbols
    FONT = {
        ' ': [0x00]*5,
        '0': [0x3E,0x51,0x49,0x45,0x3E],
        '1': [0x00,0x42,0x7F,0x40,0x00],
        '2': [0x42,0x61,0x51,0x49,0x46],
        '3': [0x21,0x41,0x45,0x4B,0x31],
        '4': [0x18,0x14,0x12,0x7F,0x10],
        '5': [0x27,0x45,0x45,0x45,0x39],
        '6': [0x3C,0x4A,0x49,0x49,0x30],
        '7': [0x01,0x71,0x09,0x05,0x03],
        '8': [0x36,0x49,0x49,0x49,0x36],
        '9': [0x06,0x49,0x49,0x29,0x1E],
        'A': [0x7E,0x11,0x11,0x11,0x7E],
        'B': [0x7F,0x49,0x49,0x49,0x36],
        'C': [0x3E,0x41,0x41,0x41,0x22],
        'D': [0x7F,0x41,0x41,0x22,0x1C],
        'E': [0x7F,0x49,0x49,0x49,0x41],
        'F': [0x7F,0x09,0x09,0x09,0x01],
        'G': [0x3E,0x41,0x49,0x49,0x7A],
        'H': [0x7F,0x08,0x08,0x08,0x7F],
        'I': [0x00,0x41,0x7F,0x41,0x00],
        'J': [0x20,0x40,0x41,0x3F,0x01],
        'K': [0x7F,0x08,0x14,0x22,0x41],
        'L': [0x7F,0x40,0x40,0x40,0x40],
        'M': [0x7F,0x02,0x0C,0x02,0x7F],
        'N': [0x7F,0x04,0x08,0x10,0x7F],
        'O': [0x3E,0x41,0x41,0x41,0x3E],
        'P': [0x7F,0x09,0x09,0x09,0x06],
        'Q': [0x3E,0x41,0x51,0x21,0x5E],
        'R': [0x7F,0x09,0x19,0x29,0x46],
        'S': [0x46,0x49,0x49,0x49,0x31],
        'T': [0x01,0x01,0x7F,0x01,0x01],
        'U': [0x3F,0x40,0x40,0x40,0x3F],
        'V': [0x1F,0x20,0x40,0x20,0x1F],
        'W': [0x3F,0x40,0x38,0x40,0x3F],
        'X': [0x63,0x14,0x08,0x14,0x63],
        'Y': [0x07,0x08,0x70,0x08,0x07],
        'Z': [0x61,0x51,0x49,0x45,0x43],
        ':': [0x00,0x36,0x36,0x00,0x00],
        '-': [0x08,0x08,0x08,0x08,0x08],
        '!': [0x00,0x00,0x5F,0x00,0x00],
        '>': [0x41,0x22,0x14,0x08,0x00],
        '<': [0x00,0x08,0x14,0x22,0x41],
        'x': [0x36,0x08,0x08,0x08,0x36],
        'p': [0x78,0x14,0x14,0x14,0x08],
        't': [0x08,0x3E,0x48,0x28,0x10],
        's': [0x48,0x54,0x54,0x54,0x24],
        'W': [0x3F,0x40,0x38,0x40,0x3F],
    }
    cols = FONT.get(ch.upper(), FONT.get(ch, [0x00]*5))
    scale = 2
    for col_i, col_bits in enumerate(cols):
        for row_i in range(7):
            c = color if (col_bits >> row_i) & 1 else bg
            lcd_rect(x + col_i * scale, y + row_i * scale, scale, scale, c)

def lcd_text(x, y, text, color=C_WHITE, bg=C_BLACK):
    """Draw string at pixel position."""
    cx = x
    for ch in text:
        if cx + 12 > LCD_W:
            break
        lcd_char(cx, y, ch, color, bg)
        cx += 12   # 5px * 2scale + 2 gap

def lcd_draw_menu():
    lcd_fill(C_BLACK)
    lcd_text(100, 100, "SPACE SHOOTER", C_CYAN)
    lcd_text(60,  160, "PRESS BOTH JOYSTICK", C_WHITE)
    lcd_text(80,  185, "BUTTONS TO START", C_WHITE)

def lcd_draw_waiting():
    lcd_fill(C_BLACK)
    lcd_text(80, 140, "WAITING FOR P2", C_YELLOW)

def lcd_draw_connected():
    lcd_fill(C_BLACK)
    lcd_text(70, 140, "P2 CONNECTED!", C_GREEN)

def lcd_draw_both_press():
    lcd_fill(C_BLACK)
    lcd_text(40,  120, "BOTH PLAYERS PRESS", C_YELLOW)
    lcd_text(80,  150, "JOYSTICK B7 TO", C_YELLOW)
    lcd_text(120, 180, "START!", C_WHITE)

def lcd_draw_countdown(n):
    lcd_fill(C_BLACK)
    lcd_text(210, 130, str(n), C_WHITE)

def lcd_draw_gameover(w):
    lcd_fill(C_BLACK)
    lcd_text(120, 100, "GAME OVER", C_RED)
    lcd_text(80,  150, w + " WINS!", C_YELLOW)
    lcd_text(60,  200, str(p1_name)+":"+str(p1_score)+"  "+str(p2_name)+":"+str(p2_score), C_WHITE)

def lcd_render_frame():
    """Render one game frame — optimized: no full clear, draw over bg."""
    # Background
    lcd_fill(C_DARK)

    # P1 ship (green)
    lcd_rect(p1_x, p1_y, SHIP_W, SHIP_H, C_GREEN)

    # P2 ship (red)
    lcd_rect(p2_x, p2_y, SHIP_W, SHIP_H, C_RED)

    # Bullets
    for b in bullets:
        c = C_CYAN if b[2] == 1 else C_YELLOW
        lcd_rect(b[0], b[1], BULLET_W, BULLET_H, c)

    # HUD — lives top bar
    lcd_text(4,   4, p1_name + " " + str(p1_lives) + "HP", C_GREEN, C_DARK)
    lcd_text(320, 4, p2_name + " " + str(p2_lives) + "HP", C_RED,   C_DARK)

# =============================================================================
# MODULE 1 — Pi A STARTUP & JOIN
# =============================================================================

def startup():
    global spi_obj, spi_lcd, bus, log_fh

    # Init GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [GPIO_SHOOT, GPIO_MENU, GPIO_BTN_B2, GPIO_BTN_B3,
                GPIO_BTN_B4, GPIO_BTN_B5, GPIO_BTN_B6, GPIO_JOY_BB]:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(GPIO_LCD_DC,  GPIO.OUT)
    GPIO.setup(GPIO_LCD_RST, GPIO.OUT)

    # SPI for Pi B communication (CE0)
    spi_obj = spidev.SpiDev()
    spi_obj.open(SPI_BUS, SPI_DEV_SLAVE)
    spi_obj.max_speed_hz = SPI_SPEED_HZ
    spi_obj.mode = 0

    # SPI for LCD (CE1)
    spi_lcd = spidev.SpiDev()
    spi_lcd.open(SPI_BUS, SPI_DEV_LCD)
    spi_lcd.max_speed_hz = SPI_SPEED_HZ
    spi_lcd.mode = 0

    # I2C ADC
    try:
        bus = smbus.SMBus(I2C_BUS)
    except Exception:
        bus = None

    # LCD init
    lcd_init()

    # Logger
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        write_hdr = not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0
        log_fh = open(LOG_PATH, "a", newline="")
        if write_hdr:
            csv.writer(log_fh).writerow(
                ["timestamp", "fps", "cpu_temp", "spi_latency_ms",
                 "p1_lives", "p2_lives", "error"])
            log_fh.flush()
    except OSError:
        log_fh = None
        print("[WARN] Storage unavailable — logging disabled.")

    # Show menu
    lcd_draw_menu()

    # Step 1: Send JOIN_REQUEST, wait for JOIN_ACK from Pi B
    print("[Pi A] Sending JOIN_REQUEST to Pi B...")
    lcd_draw_waiting()
    while True:
        _spi_slave_send([0xA1] + [0x00] * 8)
        time.sleep(0.1)
        resp = _spi_slave_recv()
        if resp and resp[0] == 0xA2:
            break
        time.sleep(0.1)

    lcd_draw_connected()
    time.sleep(0.5)

    # Step 2: Wait for BOTH players to press B7 simultaneously
    # Pi A checks its own B7, polls Pi B for its B7 state
    print("[Pi A] Waiting for both players to press B7...")
    lcd_draw_both_press()

    while True:
        # Ask Pi B: is your B7 pressed?
        _spi_slave_send([0xB0] + [0x00] * 8)
        time.sleep(0.02)
        resp = _spi_slave_recv()
        pb_ready = resp and resp[0] == 0xB1   # Pi B B7 pressed

        pa_ready = not GPIO.input(GPIO_SHOOT)  # Pi A B7 pressed

        if pa_ready and pb_ready:
            time.sleep(0.05)   # debounce
            # Confirm to Pi B: both pressed, game starting
            _spi_slave_send([0xB2] + [0x00] * 8)
            break
        time.sleep(0.02)

    print("[Pi A] Both buttons confirmed. Starting game.")

    # Countdown
    for n in [3, 2, 1]:
        lcd_draw_countdown(n)
        time.sleep(1)

    game_loop()


# =============================================================================
# MODULE 3 — GAME LOOP
# =============================================================================

def game_loop():
    global p1_lives, p2_lives, p1_score, p2_score
    global p1_x, p1_y, p2_x, p2_y
    global bullets, game_state, winner

    frame_error = "None"

    while game_state == "playing":
        t0 = time.time()
        frame_error = "None"

        # 1. Read P1 joystick
        p1_jx, p1_jy, p1_shoot = _read_joystick()

        # 2. Get Pi B data
        t_spi = time.time()
        p2_jx, p2_jy, p2_btn, spi_ok = spi_master()
        spi_lat = (time.time() - t_spi) * 1000
        if not spi_ok:
            frame_error = "SPI_ERR"

        # 3. Update ship positions
        p1_dx = _norm(p1_jx);  p1_dy = _norm(p1_jy)
        p2_dx = _norm(p2_jx);  p2_dy = _norm(p2_jy)

        global p1_x, p1_y, p2_x, p2_y
        p1_x = _clamp(int(p1_x + p1_dx * SHIP_SPEED), SHIP_W, LCD_W // 2 - SHIP_W)
        p1_y = _clamp(int(p1_y + p1_dy * SHIP_SPEED), SHIP_H, LCD_H - SHIP_H)
        p2_x = _clamp(int(p2_x + p2_dx * SHIP_SPEED), LCD_W // 2 + SHIP_W, LCD_W - SHIP_W)
        p2_y = _clamp(int(p2_y + p2_dy * SHIP_SPEED), SHIP_H, LCD_H - SHIP_H)

        # 4. Bullets
        if p1_shoot:
            bullets.append([p1_x + SHIP_W, p1_y + SHIP_H // 2, 1,  1])
        if p2_btn & 0x01:
            bullets.append([p2_x,          p2_y + SHIP_H // 2, 2, -1])

        moved = []
        for b in bullets:
            b[0] += b[3] * BULLET_SPEED
            if 0 <= b[0] <= LCD_W:
                moved.append(b)
        bullets = moved

        # 5-6. Collision
        alive = []
        for b in bullets:
            hit = False
            if b[2] == 1:
                if _overlap(b[0], b[1], BULLET_W, BULLET_H, p2_x, p2_y, SHIP_W, SHIP_H):
                    p2_lives -= 1;  p1_score += 1;  hit = True
            else:
                if _overlap(b[0], b[1], BULLET_W, BULLET_H, p1_x, p1_y, SHIP_W, SHIP_H):
                    p1_lives -= 1;  p2_score += 1;  hit = True
            if not hit:
                alive.append(b)
        bullets = alive

        # 7. Win condition
        if p1_lives <= 0:
            winner = p2_name;  game_state = "game_over"
        elif p2_lives <= 0:
            winner = p1_name;  game_state = "game_over"

        if game_state == "game_over":
            break

        # 9. Render
        lcd_render_frame()

        # 11. Logger
        fps = 1.0 / max(time.time() - t0, 0.001)
        data_logger(fps, spi_lat, frame_error)

        # 12. Frame timing
        elapsed = time.time() - t0
        if FRAME_TIME - elapsed > 0:
            time.sleep(FRAME_TIME - elapsed)

    # Game over
    _spi_slave_send([0xEE] + [0x00] * 8)
    lcd_draw_gameover(winner)
    data_logger_flush()
    time.sleep(5)
    GPIO.cleanup()


# =============================================================================
# MODULE 4 — SPI MASTER
# =============================================================================

def spi_master():
    global p2_last_x, p2_last_y, p2_last_btn, spi_miss

    for _ in range(2):
        try:
            req = [0xAA] + [0x00] * 8
            raw = spi_obj.xfer2(req, SPI_SPEED_HZ, 0)

            if raw[0] != PKT_HEADER:
                continue

            x_h, x_l, y_h, y_l, btn = raw[1], raw[2], raw[3], raw[4], raw[5]
            cs_calc = x_h ^ x_l ^ y_h ^ y_l ^ btn
            if cs_calc != raw[8]:
                continue

            x_val = (x_h << 8) | x_l
            y_val = (y_h << 8) | y_l

            _send_game_state()

            p2_last_x, p2_last_y, p2_last_btn = x_val, y_val, btn
            spi_miss = 0
            return x_val, y_val, btn, True

        except Exception:
            continue

    spi_miss += 1
    if spi_miss > 2:
        return 32767, 32767, 0, False
    return p2_last_x, p2_last_y, p2_last_btn, False


def _send_game_state():
    w = 0x01 if winner == p1_name else (0x02 if winner == p2_name else 0x00)
    s = 0xEE if game_state == "game_over" else 0x01
    d = [s, p1_lives & 0xFF, p2_lives & 0xFF,
         (p1_score >> 8) & 0xFF, p1_score & 0xFF,
         (p2_score >> 8) & 0xFF, p2_score & 0xFF,
         w, 0x00]
    cs = 0
    for b in d[:-1]: cs ^= b
    d[8] = cs
    try:
        spi_obj.xfer2(d, SPI_SPEED_HZ, 0)
    except Exception:
        pass


# =============================================================================
# MODULE 6 — DATA LOGGER
# =============================================================================

def data_logger(fps, spi_ms, error="None"):
    global log_buffer
    ts  = time.strftime("%H:%M:%S")
    cpu = _cpu_temp()
    log_buffer.append([ts, f"{fps:.1f}", f"{cpu:.1f}", f"{spi_ms:.2f}",
                        p1_lives, p2_lives, error])
    if len(log_buffer) >= LOG_BUF_MAX:
        _flush()

def data_logger_flush():
    _flush()
    if log_fh:
        try: log_fh.close()
        except Exception: pass

def _flush():
    global log_buffer
    if not log_fh or not log_buffer:
        return
    try:
        csv.writer(log_fh).writerows(log_buffer)
        log_fh.flush()
        log_buffer = []
    except OSError:
        log_buffer = []


# =============================================================================
# HELPERS
# =============================================================================

def _read_joystick():
    x, y = 32767, 32767
    if bus:
        try:
            # ADS1115 single-shot CH0 (X)
            bus.write_i2c_block_data(ADC_ADDR, 0x01, [0xC3, 0x83])
            time.sleep(0.002)
            r = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
            x = max(0, ((r[0] << 8) | r[1]) & 0xFFFF)
            # CH1 (Y)
            bus.write_i2c_block_data(ADC_ADDR, 0x01, [0xD3, 0x83])
            time.sleep(0.002)
            r = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
            y = max(0, ((r[0] << 8) | r[1]) & 0xFFFF)
        except Exception:
            pass
    shoot = not GPIO.input(GPIO_SHOOT)
    return x, y, shoot

def _norm(v):
    d = v - 32767
    if abs(d) < DEADZONE: return 0.0
    if d > 0: return (d - DEADZONE) / (32767 - DEADZONE)
    return (d + DEADZONE) / (32767 - DEADZONE)

def _clamp(v, lo, hi): return max(lo, min(hi, v))

def _overlap(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx+bw and ax+aw > bx and ay < by+bh and ay+ah > by

def _cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000.0
    except Exception:
        return 0.0

def _spi_slave_send(data):
    try: spi_obj.xfer2(data, SPI_SPEED_HZ, 0)
    except Exception: pass

def _spi_slave_recv():
    try: return spi_obj.xfer2([0x00] * 9, SPI_SPEED_HZ, 0)
    except Exception: return None


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        startup()
    except KeyboardInterrupt:
        print("\n[Pi A] Stopped.")
    finally:
        data_logger_flush()
        try: GPIO.cleanup()
        except Exception: pass
        try: spi_obj.close()
        except Exception: pass
        try: spi_lcd.close()
        except Exception: pass

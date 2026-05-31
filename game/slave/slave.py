#!/usr/bin/env python3
# =============================================================================
# slave.py — Pi B (Slave Node)
# Space Shooter via SPI — THD Case Study A06
# Pi 1 B+, BCM2835, ARMv6 700MHz, single core
# Role: P2 joystick reading + SPI response to Pi A — NO display, NO game logic
# =============================================================================

import RPi.GPIO as GPIO
import spidev
import smbus
import time
import threading

# =============================================================================
# HARDWARE CONSTANTS — matched to schematic
# =============================================================================

SPI_BUS       = 0
SPI_DEVICE    = 0            # CE0 (GPIO8) — connected to Pi A CE0
SPI_SPEED_HZ  = 1_000_000

I2C_BUS       = 1            # GPIO2/GPIO3 — I2C-1 on Pi 1 B+
ADC_ADDR      = 0x48         # ADS1x15, ADDR → GND

# GPIO — Controller 2 (schematic verified, same pin mapping as Controller 1)
GPIO_CE0_MON  = 8            # Pin 24 — monitor CE0 from Pi A
GPIO_SHOOT    = 5            # Pin 29 — Joystick B7 (shoot)
GPIO_MENU     = 12           # Pin 32 — B1 Green
GPIO_BTN_B2   = 13           # Pin 33 — B2 Pink
GPIO_BTN_B3   = 19           # Pin 35 — B3 White
GPIO_BTN_B4   = 16           # Pin 36 — B4 Yellow
GPIO_BTN_B5   = 26           # Pin 37 — B5 Blue
GPIO_BTN_B6   = 20           # Pin 38 — B6 Red
GPIO_JOY_BB   = 6            # Pin 31 — Joystick BB

PKT_SIZE      = 9
PKT_HEADER    = 0xFF
AXIS_CENTER   = 32767
DEADZONE      = 2000

# =============================================================================
# GLOBAL STATE
# =============================================================================

spi = None
bus = None

_jx   = AXIS_CENTER
_jy   = AXIS_CENTER
_btn  = 0

_game_state = 0x01    # 0x01=playing, 0xEE=game_over
_p1_lives   = 3
_p2_lives   = 3
_p1_score   = 0
_p2_score   = 0
_winner     = 0x00

_stop = threading.Event()

# =============================================================================
# MODULE 2 — Pi B STARTUP & JOIN
# =============================================================================

def startup():
    global spi, bus

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(GPIO_CE0_MON, GPIO.IN)
    for pin in [GPIO_SHOOT, GPIO_MENU, GPIO_BTN_B2, GPIO_BTN_B3,
                GPIO_BTN_B4, GPIO_BTN_B5, GPIO_BTN_B6, GPIO_JOY_BB]:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # NOTE: Pi 1 hardware SPI is master-only.
    # Pi B uses spidev in a cooperative polling mode:
    # it monitors CE0 (GPIO8) to detect when Pi A initiates a transaction,
    # then immediately responds via xfer2. Both Pis use mode=0.
    # Pi A drives SCLK — Pi B's spidev call is timed to coincide.
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0

    try:
        bus = smbus.SMBus(I2C_BUS)
    except Exception:
        bus = None

    print("[Pi B] Ready. Waiting for JOIN_REQUEST from Pi A...")

    # Wait for JOIN_REQUEST (0xA1)
    while True:
        try:
            r = spi.xfer2([0x00] * 9, SPI_SPEED_HZ, 0)
            if r[0] == 0xA1:
                break
        except Exception:
            pass
        time.sleep(0.05)

    # Send JOIN_ACK (0xA2)
    try:
        spi.xfer2([0xA2] + [0x00] * 8, SPI_SPEED_HZ, 0)
    except Exception:
        pass
    print("[Pi B] JOIN_ACK sent. Waiting for game start...")

    # Wait for first non-zero SPI data (game started)
    while True:
        try:
            r = spi.xfer2([0x00] * 9, SPI_SPEED_HZ, 0)
            if any(b != 0 for b in r):
                break
        except Exception:
            pass
        time.sleep(0.05)

    print("[Pi B] Game started. Entering SPI slave loop.")
    spi_slave()


# =============================================================================
# MODULE 5 — SPI SLAVE LOOP
# =============================================================================

def spi_slave():
    _stop.clear()

    # Start joystick polling thread (≥100 Hz)
    t = threading.Thread(target=_joy_poll, daemon=True)
    t.start()

    print("[Pi B] SPI slave loop running.")

    while not _stop.is_set():

        # Wait for CE0 LOW — Pi A is starting a transaction
        if not _wait_ce0_low():
            continue   # timeout — loop again

        # Snapshot current joystick values
        jx  = _jx
        jy  = _jy
        btn = _btn

        # Build 9-byte response packet
        x_h = (jx >> 8) & 0xFF
        x_l =  jx       & 0xFF
        y_h = (jy >> 8) & 0xFF
        y_l =  jy       & 0xFF
        cs  = x_h ^ x_l ^ y_h ^ y_l ^ btn
        pkt = [PKT_HEADER, x_h, x_l, y_h, y_l, btn, 0x00, 0x00, cs]

        # Send packet, receive game state simultaneously (full-duplex)
        try:
            raw = spi.xfer2(pkt, SPI_SPEED_HZ, 0)
        except Exception:
            continue

        # Parse game state from Pi A
        _parse_state(raw)

        # Game over?
        if _game_state == 0xEE:
            print("[Pi B] Game over. Stopping.")
            _stop.set()
            break

    _cleanup()


# =============================================================================
# HELPERS
# =============================================================================

def _wait_ce0_low():
    """Wait up to 100ms for CE0 to go LOW (Pi A starts transaction)."""
    deadline = time.time() + 0.1
    while GPIO.input(GPIO_CE0_MON) == GPIO.HIGH:
        if time.time() > deadline:
            return False
    return True


def _joy_poll():
    """Background thread: read joystick at ~125 Hz."""
    global _jx, _jy, _btn
    while not _stop.is_set():
        _jx, _jy = _read_adc()
        _btn = _read_btns()
        time.sleep(0.008)   # 8 ms = ~125 Hz


def _read_adc():
    x, y = AXIS_CENTER, AXIS_CENTER
    if not bus:
        return x, y
    try:
        # CH0 → X
        bus.write_i2c_block_data(ADC_ADDR, 0x01, [0xC3, 0x83])
        time.sleep(0.002)
        r = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
        x = max(0, ((r[0] << 8) | r[1]) & 0xFFFF)
        # CH1 → Y
        bus.write_i2c_block_data(ADC_ADDR, 0x01, [0xD3, 0x83])
        time.sleep(0.002)
        r = bus.read_i2c_block_data(ADC_ADDR, 0x00, 2)
        y = max(0, ((r[0] << 8) | r[1]) & 0xFFFF)
    except Exception:
        pass
    return x, y


def _read_btns():
    """bit0 = shoot (GPIO5/B7)."""
    btn = 0
    if not GPIO.input(GPIO_SHOOT):
        btn |= 0x01
    return btn


def _parse_state(raw):
    global _game_state, _p1_lives, _p2_lives, _p1_score, _p2_score, _winner
    if len(raw) < PKT_SIZE:
        return
    s, p1l, p2l = raw[0], raw[1], raw[2]
    p1s = (raw[3] << 8) | raw[4]
    p2s = (raw[5] << 8) | raw[6]
    w   = raw[7]
    cs_recv = raw[8]
    cs_calc = s ^ p1l ^ p2l ^ raw[3] ^ raw[4] ^ raw[5] ^ raw[6] ^ w
    if cs_calc != cs_recv:
        return   # discard corrupted packet
    _game_state = s
    _p1_lives   = p1l
    _p2_lives   = p2l
    _p1_score   = p1s
    _p2_score   = p2s
    _winner     = w


def _cleanup():
    global spi
    try:
        if spi: spi.close()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass
    print("[Pi B] Cleanup done.")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        startup()
    except KeyboardInterrupt:
        print("\n[Pi B] Stopped.")
        _stop.set()
    finally:
        _cleanup()

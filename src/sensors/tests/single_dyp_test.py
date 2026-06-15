import time
import serial

# Configuration
# On Raspberry Pi 5, the primary GPIO hardware serial port is /dev/ttyAMA0
SERIAL_PORT = '/dev/ttyAMA0'
BAUD_RATE = 115200


def read_dyp_sensor():
    print("=========================================")
    print("  DYP-A22 UART Auto Mode Reader (Pi 5)   ")
    print("=========================================")

    try:
        # Initialize Serial Port Connection
        with serial.Serial(SERIAL_PORT, baudrate=BAUD_RATE, timeout=1) as ser:
            # Flush any old data in the buffer
            ser.reset_input_buffer()

            while True:
                # Read 1 byte at a time looking for the 0xFF header frame
                if ser.read(1) == b'\xff':
                    # Once header is found, immediately pull the remaining 3 data bytes
                    data = ser.read(3)

                    if len(data) == 3:
                        high_byte = data[0]
                        low_byte = data[1]
                        checksum = data[2]

                        # Validate the 8-bit checksum calculation
                        calculated_checksum = (0xFF + high_byte + low_byte) & 0xFF

                        if calculated_checksum == checksum:
                            # Shift bits to calculate overall distance in millimeters
                            distance_mm = (high_byte << 8) + low_byte

                            if distance_mm == 0:
                                print("Reading Error: Object out of range.")
                            else:
                                distance_cm = distance_mm / 10.0
                                print(f"Distance: {distance_cm:.1f} cm")
                        else:
                            print("Warning: Checksum mismatch. Corrupted data frame.")

                # Tiny sleep interval to prevent high CPU utilization
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nExiting script safely.")
    except Exception as e:
        print(f"\nFatal Error: {e}")
        print("Troubleshooting checklist:")
        print("1. Verify VCC is connected to a 3.3V pin, NOT a 5V pin.")
        print("2. Confirm Pin 8 (TX) goes to Sensor RX, and Pin 10 (RX) goes to Sensor TX.")
        print("3. Check that Serial Port Hardware is enabled via raspi-config.")


if __name__ == "__main__":
    read_dyp_sensor()
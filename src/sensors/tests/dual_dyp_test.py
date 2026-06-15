import time
import serial

# Define the two separate hardware ports
PORT_SENSOR_1 = '/dev/ttyAMA0'
PORT_SENSOR_2 = '/dev/ttyAMA4'

# Set to 9600 if your sensors used 9600 during your Arduino bench test
BAUD_RATE = 115200


def read_dual_sensors():
    print("DYP-A22 Dual Sensor Monitor")

    try:
        # Open both hardware serial ports simultaneously
        ser1 = serial.Serial(PORT_SENSOR_1, baudrate=BAUD_RATE, timeout=0.05)
        ser2 = serial.Serial(PORT_SENSOR_2, baudrate=BAUD_RATE, timeout=0.05)

        # Clear out any stale boot data
        ser1.reset_input_buffer()
        ser2.reset_input_buffer()


        while True:
            # --- PROCESS SENSOR 1 ---
            if ser1.in_waiting >= 4:
                if ser1.read(1) == b'\xff':  # Look for Header
                    data1 = ser1.read(3)
                    if len(data1) == 3:
                        # Validate Checksum
                        if ((0xFF + data1[0] + data1[1]) & 0xFF) == data1[2]:
                            dist1 = ((data1[0] << 8) + data1[1]) / 10.0
                            print(f"[Sensor 1]: {dist1:6.1f} cm")
                        else:
                            print("[Sensor 1]: Checksum error")

            # --- PROCESS SENSOR 2 ---
            if ser2.in_waiting >= 4:
                if ser2.read(1) == b'\xff':  # Look for Header
                    data2 = ser2.read(3)
                    if len(data2) == 3:
                        # Validate Checksum
                        if ((0xFF + data2[0] + data2[1]) & 0xFF) == data2[2]:
                            dist2 = ((data2[0] << 8) + data2[1]) / 10.0
                            # Tabbed right for visual clarity in the terminal window
                            print(f"\t\t\t[Sensor 2]: {dist2:6.1f} cm")
                        else:
                            print("\t\t\t[Sensor 2]: Checksum error")

            # Small delay to keep CPU usage low
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nTerminating sensor script safely.")
    except Exception as e:
        print(f"\nError running ports: {e}")
    finally:
        # Cleanly shut down connections upon exit
        try:
            ser1.close()
            ser2.close()
        except:
            pass


if __name__ == "__main__":
    read_dual_sensors()
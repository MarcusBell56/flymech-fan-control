import pywinusb.hid as hid
import wmi
import time
import sys
import os
import datetime
import socket

# --- Configuration ---
DEVICE_VID = 0x37d7
DEVICE_PID = 0x1002
CHECK_INTERVAL = 3
SINGLE_INSTANCE_PORT = 64512

# File logging disabled per user request
# SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# LOG_FILE = os.path.join(SCRIPT_DIR, "run_log.txt")

def log(msg, overwrite=False):
    """
    Standard logging function.
    Prints to console only.
    overwrite=True: Overwrites the current line (Dashboard style).
    overwrite=False: Prints on a new line (Event/Error style).
    """
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    
    # Write to console
    try:
        if sys.stdout:
            if overwrite:
                # \r returns cursor to start, spaces padding clears previous text
                sys.stdout.write(f"\r{formatted_msg:<80}")
                sys.stdout.flush()
            else:
                # Ensure we start on a new line if clearing previous overwrite
                sys.stdout.write(f"\r{formatted_msg:<80}\n")
                sys.stdout.flush()
    except:
        pass

class FlydigiController:
    def __init__(self):
        self.all_interfaces = []
        self.last_mode = -1
        self.last_rpm = -1
        self.first_run = True
        self.last_device_temp = None
        self.last_real_rpm = None
        
    def _input_handler(self, data):
        """Callback for receiving data."""
        try:
            if len(data) > 10 and data[1] == 0x5A and data[2] == 0xA5:
                cmd = data[3]
                if cmd == 0xEF:
                    # Parse Device Status
                    self.last_device_temp = data[4]
                    rpm_low = data[8]
                    rpm_high = data[9]
                    self.last_real_rpm = rpm_low + (rpm_high << 8)
        except:
            pass
            
    def connect(self):
        """Scan and connect."""
        log("正在尝试连接设备...", overwrite=False)
        try:
            filter = hid.HidDeviceFilter(vendor_id=DEVICE_VID, product_id=DEVICE_PID)
            devices = filter.get_devices()
            
            if devices:
                self.all_interfaces = devices
                log(f"✅ 已连接 {len(devices)} 个接口", overwrite=False)
                
                for dev in self.all_interfaces:
                    try:
                        if not dev.is_opened():
                            dev.open()
                        dev.set_raw_data_handler(self._input_handler)
                    except:
                        pass
                return True
            else:
                log("❌ 未找到设备", overwrite=False)
                return False
        except Exception as e:
            log(f"连接异常: {e}", overwrite=False)
            return False

    def send_packet(self, payload):
        checksum = sum(payload[3:]) & 0xFF
        payload.append(checksum)
        target_length = 25
        padding = [0x00] * (target_length - len(payload))
        final_report = payload + padding
        
        success = False
        for dev in self.all_interfaces:
            try:
                if not dev.is_opened(): dev.open()
                out_reports = dev.find_output_reports()
                if out_reports:
                    out_reports[0].set_raw_data(final_report)
                    out_reports[0].send()
                    success = True
            except:
                pass
        return success

    def set_fan(self, mode, rpm, force=False):
        if not self.all_interfaces:
            if not self.connect(): return

        # Send packet if forced OR state changed
        if force or mode != self.last_mode or rpm != self.last_rpm:
            rpm_low = rpm & 0xFF
            rpm_high = (rpm >> 8) & 0xFF
            payload = [0x00, 0x5A, 0xA5, 0x26, 0x05, mode, rpm_low, rpm_high]
            
            if self.send_packet(payload):
                self.last_mode = mode
                self.last_rpm = rpm
                # State change is significant, force a new line log
                # log(f"指令发送成功: {rpm} RPM (Mode {mode})", overwrite=False)
            else:
                # log("⚠️ 指令发送失败，准备重连", overwrite=False)
                self.all_interfaces = [] 

    def probe_status(self):
        if not self.all_interfaces: return
        payload = [0x00, 0x5A, 0xA5, 0x24, 0x05, 0x00, 0x00, 0x00]
        if not self.send_packet(payload):
            self.all_interfaces = []

def get_cpu_temp():
    try:
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        sensors = w.Sensor()
        for sensor in sensors:
            if sensor.SensorType == u'Temperature' and u'CPU' in sensor.Name:
                if 'Package' in sensor.Name:
                    return sensor.Value
        return None
    except:
        return None

def get_smart_strategy(temp):
    if temp < 50: return (0, 1300)
    elif temp < 60: return (0, 1700)
    elif temp < 70: return (1, 2100)
    elif temp < 80: return (1, 2400)
    else: return (1, 2700)

def main():
    # Console setup
    os.system("title 飞智智能管家 - 运行面板")
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass

    # Single Instance Check
    global instance_socket
    try:
        instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance_socket.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))
        instance_socket.listen(0)
    except socket.error:
        print("⚠️ 程序已在后台运行中，请勿重复启动！")
        time.sleep(2)
        sys.exit(0)

    log("🤖 飞智智能管家已启动 (仪表盘模式)", overwrite=False)
    
    fan = FlydigiController()
    while not fan.connect():
        log("等待设备连接...", overwrite=False)
        time.sleep(5)
    
    # 动画光标
    spinner = ['|', '/', '-', '\\']
    spinner_idx = 0

    while True:
        try:
            # 1. Read Temps
            cpu_temp = get_cpu_temp()
            
            if cpu_temp is None:
                # Still log to console so user knows it's waiting
                log("⏳ 等待 OpenHardwareMonitor...", overwrite=True)
                time.sleep(5)
                continue
                
            # 2. Logic
            mode, target_rpm = get_smart_strategy(cpu_temp)
            
            # 3. Actions
            fan.set_fan(mode, target_rpm, force=fan.first_run)
            fan.probe_status()
            
            if fan.first_run: fan.first_run = False
            
            # 4. 打印单行状态 (仪表盘风格)
            # Format data for display
            # 既然可能是使用率，就显示通用点 "Val: 11" 
            dev_val_str = f"{fan.last_device_temp}" if fan.last_device_temp is not None else "--"
            real_rpm_str = f"{fan.last_real_rpm}" if fan.last_real_rpm is not None else "--"
            mode_str = "静音" if mode == 0 else "标准"
            
            # 覆盖同一行打印
            log_msg = (
                f"{spinner[spinner_idx]} "
                f"CPU: {cpu_temp:.1f}°C | "
                f"设备反馈: {dev_val_str} | "
                f"转速: {target_rpm} (实测 {real_rpm_str}) | "
                f"模式: {mode_str}"
            )
            
            log(log_msg, overwrite=True)
            
            spinner_idx = (spinner_idx + 1) % 4
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            log("程序手动退出", overwrite=False)
            break
        except Exception as e:
            log(f"❌ 错误: {e}", overwrite=False)
            time.sleep(5)
            fan.all_interfaces = []

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"💥 程序崩溃: {e}", overwrite=False)
        os.system("pause")
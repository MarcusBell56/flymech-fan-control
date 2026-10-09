import pywinusb.hid as hid
import time
import threading

class FlydigiBS2:
    # 您的设备 ID
    VID = 0x37d7
    PID = 0x1002
    
    # 协议常量
    REPORT_SIZE = 25
    HEADER = [0x5A, 0xA5]
    
    def __init__(self):
        self.device = None
        self.last_temp = 0 # 存储设备回传的制冷片温度
        self._running = False

    def connect(self):
        """连接设备"""
        filter = hid.HidDeviceFilter(vendor_id=self.VID, product_id=self.PID)
        devices = filter.get_devices()
        
        if not devices:
            raise Exception("未找到设备，请检查 USB 连接")
            
        self.device = devices[0]
        self.device.open()
        
        # 绑定数据接收回调（用于读温度）
        self.device.set_raw_data_handler(self._input_handler)
        print(f"已连接: {self.device.product_name}")

    def _input_handler(self, data):
        """
        处理设备发回来的数据
        这里是逆向的重点：我们需要找出哪个字节代表温度
        """
        # data 通常是一个 list [ReportID, 5A, A5, ...]
        # 调试时取消下面这行的注释，看看原始数据长什么样
        # print(f"收到数据: {data}")
        
        # 飞智通用协议解析尝试：
        # 假设 data[1]=0x5A, data[2]=0xA5 (因为 data[0] 是 report ID)
        if len(data) > 5 and data[1] == 0x5A:
            # 根据经验，温度通常在第 4 或 5 个字节
            # 这里的 index 需要您实际看 log 确认，暂时假设是 index 4
            # 这里的温度是制冷片表面的温度，不是 CPU 温度
            raw_temp = data[4] 
            self.last_temp = raw_temp

    # rpm: 转速 1300-静音1档，1700-静音2档，1900-静音3档，2100-标准1档，2400-标准2档，2700-标准3档
    def set_speed(self, rpm, mode=1):
        """
        发送转速指令
        mode: 0=静音, 1=标准, 2=超频(推测)
        rpm: 目标转速
        """
        if not self.device:
            return

        # 1. 准备数据 Payload
        # [0x26, 0x05, 模式, RPM低, RPM高]
        rpm_low = rpm & 0xFF
        rpm_high = (rpm >> 8) & 0xFF
        
        payload = [0x26, 0x05, mode, rpm_low, rpm_high]
        
        # 计算校验和
        checksum = sum(payload) & 0xFF
        
        # 2. 拼接完整包: [ReportID] + [Header] + [Payload] + [Checksum]
        # ReportID 在 pywinusb 中通常是单独处理的，但 raw_data 最好带上
        full_cmd = [0x00] + self.HEADER + payload + [checksum]
        
        # 3. 补齐到 25 字节
        padding = [0x00] * (self.REPORT_SIZE - len(full_cmd))
        final_report = full_cmd + padding
        
        # 4. 发送
        try:
            out_reports = self.device.find_output_reports()
            if out_reports:
                out_reports[0].set_raw_data(final_report)
                out_reports[0].send()
            else:
                # 备用发送方案
                self.device.write(final_report[1:]) # 去掉 ReportID 发送试试
        except Exception as e:
            print(f"发送指令失败: {e}")

    def close(self):
        if self.device:
            self.device.close()

# --- 使用示例 ---
if __name__ == "__main__":
    fan = FlydigiBS2()
    try:
        fan.connect()
        
        # 测试：设为 2500 转
        print("设置转速: 2500 RPM")
        fan.set_speed(2500)
        
        print("开始监控设备状态 (按 Ctrl+C 退出)...")
        while True:
            # 打印读到的设备温度
            # 注意：如果一直是 0，说明需要分析 _input_handler 里的 index
            print(f"\r当前制冷片温度: {fan.last_temp}℃", end="")
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n退出程序")
    except Exception as e:
        print(f"\n错误: {e}")
    finally:
        fan.close()
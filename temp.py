import wmi
import time

def get_cpu_temp_ohm():
    try:
        # 连接到 OpenHardwareMonitor 暴露出来的 WMI 空间
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        
        # 获取所有传感器信息
        sensors = w.Sensor()
        
        cpu_temp = 0
        found = False
        
        for sensor in sensors:
            # 筛选：硬件类型是 CPU，传感器类型是 Temperature
            if sensor.SensorType == u'Temperature' and u'CPU' in sensor.Name:
                print(f"发现传感器 [{sensor.Name}]: {sensor.Value}°C")
                # 通常取 CPU Package 或 CPU Core #1 的温度
                if 'Package' in sensor.Name:
                    cpu_temp = sensor.Value
                    found = True
                elif not found: # 如果没找到 Package，就拿第一个核心温度顶替
                    cpu_temp = sensor.Value
        
        return cpu_temp

    except wmi.x_wmi:
        print("❌ 连接失败：请确认 OpenHardwareMonitor 软件已在后台运行！")
        return 0
    except Exception as e:
        print(f"❌ 其他错误: {e}")
        return 0

if __name__ == "__main__":
    print("正在通过 OpenHardwareMonitor 监控温度...")
    while True:
        temp = get_cpu_temp_ohm()
        if temp > 0:
            print(f"当前 CPU 核心温度: {temp}°C")
        else:
            print("等待数据...")
        time.sleep(1)
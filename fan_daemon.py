"""
Flydigi BS2PRO & MECHREVO GM7ZG7S Hardware Control Daemon
- Interactive 14/16-Point Visual Fan Curve Editor (Canvas + Table)
- Direct EC Hardware Fan Control (0 RPM / Fan Stop / Custom Curves)
- Flydigi BS2PRO Smart Cooler (800 - 4000 RPM stepless)
- MECHREVO Performance Modes (Office 35W, Gaming 50W, Turbo 95W)
- Web UI Dashboard on Port 9999
"""

import os
import sys
import time
import json
import socket
import threading
import subprocess
import glob
import ctypes
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import pywinusb.hid as hid
import wmi

DEVICE_VID = 0x37d7
DEVICE_PID = 0x1002
CHECK_INTERVAL = 1.5
WEB_PORT = 9999
SINGLE_INSTANCE_PORT = 49888
SWITCH_SCRIPT_PATH = r"E:\vs_projects\fan_control\switch_mechrevo_mode.ps1"
ACPI_DLL_PATH = r"C:\Program Files\OEM\机械革命电竞控制台\UniwillService\MyControlCenter\ACPIDriverDll.dll"
USER_FAN_TABLES_PATH = r"C:\Program Files\OEM\机械革命电竞控制台\UniwillService\MyControlCenter\UserFanTables\M1T1.json"
CURVE_CONFIG_PATH = r"E:\vs_projects\fan_control\custom_fan_curves.json"

start_time = time.time()

# 默认风扇曲线配置 (14 个核心可调点 + 2 个溢出保护点)
DEFAULT_CPU_CURVE = [
    {"id": 0, "upt": 48, "downt": 42, "duty": 0},
    {"id": 1, "upt": 54, "downt": 48, "duty": 0},
    {"id": 2, "upt": 60, "downt": 54, "duty": 0},
    {"id": 3, "upt": 65, "downt": 60, "duty": 30},
    {"id": 4, "upt": 70, "downt": 65, "duty": 35},
    {"id": 5, "upt": 75, "downt": 70, "duty": 45},
    {"id": 6, "upt": 80, "downt": 75, "duty": 55},
    {"id": 7, "upt": 83, "downt": 78, "duty": 65},
    {"id": 8, "upt": 86, "downt": 81, "duty": 75},
    {"id": 9, "upt": 89, "downt": 84, "duty": 85},
    {"id": 10, "upt": 92, "downt": 87, "duty": 90},
    {"id": 11, "upt": 95, "downt": 90, "duty": 95},
    {"id": 12, "upt": 98, "downt": 93, "duty": 100},
    {"id": 13, "upt": 100, "downt": 95, "duty": 100},
    {"id": 14, "upt": 255, "downt": 255, "duty": 100},
    {"id": 15, "upt": 255, "downt": 255, "duty": 100}
]

DEFAULT_GPU_CURVE = [
    {"id": 0, "upt": 48, "downt": 42, "duty": 0},
    {"id": 1, "upt": 54, "downt": 48, "duty": 0},
    {"id": 2, "upt": 58, "downt": 52, "duty": 0},
    {"id": 3, "upt": 61, "downt": 56, "duty": 0},
    {"id": 4, "upt": 65, "downt": 60, "duty": 30},
    {"id": 5, "upt": 70, "downt": 65, "duty": 40},
    {"id": 6, "upt": 75, "downt": 70, "duty": 50},
    {"id": 7, "upt": 78, "downt": 73, "duty": 60},
    {"id": 8, "upt": 81, "downt": 76, "duty": 70},
    {"id": 9, "upt": 84, "downt": 79, "duty": 80},
    {"id": 10, "upt": 87, "downt": 82, "duty": 90},
    {"id": 11, "upt": 90, "downt": 85, "duty": 95},
    {"id": 12, "upt": 93, "downt": 88, "duty": 100},
    {"id": 13, "upt": 95, "downt": 90, "duty": 100},
    {"id": 14, "upt": 255, "downt": 255, "duty": 100},
    {"id": 15, "upt": 255, "downt": 255, "duty": 100}
]

active_curves = {
    "cpu": list(DEFAULT_CPU_CURVE),
    "gpu": list(DEFAULT_GPU_CURVE)
}

def load_saved_curves():
    global active_curves
    if os.path.exists(CURVE_CONFIG_PATH):
        try:
            with open(CURVE_CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if "cpu" in saved and "gpu" in saved:
                    active_curves["cpu"] = saved["cpu"]
                    active_curves["gpu"] = saved["gpu"]
        except Exception:
            pass

def sync_oem_fan_tables(curves):
    """深度同步温控曲线到机械革命官方控制台的所有 UserFanTables 模板中，彻底杜绝唤醒覆盖与暴转"""
    try:
        import shutil
        all_m = glob.glob(r'C:\Program Files\OEM\**\UserFanTables\**\M*.json', recursive=True)
        for p in all_m:
            if p.endswith('.bak'): continue
            bak = p + '.bak'
            if not os.path.exists(bak):
                try: shutil.copy2(p, bak)
                except: pass
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['Activated'] = True
                data['FanControlRespective'] = True
                data['CpuTemp_DefaultMaxLevel'] = 14
                data['GpuTemp_DefaultMaxLevel'] = 14
                
                cpu_pts = []
                for item in curves.get('cpu', []):
                    cpu_pts.append({
                        'ID': item['id'],
                        'UpT': int(item['upt']),
                        'DownT': int(item['downt']),
                        'Duty': int(item['duty'])
                    })
                while len(cpu_pts) < 16:
                    last = cpu_pts[-1] if cpu_pts else {'UpT': 95, 'DownT': 90, 'Duty': 100}
                    cpu_pts.append({'ID': len(cpu_pts), 'UpT': last['UpT'], 'DownT': last['DownT'], 'Duty': last['Duty']})
                data['CPU'] = cpu_pts

                gpu_pts = []
                for item in curves.get('gpu', []):
                    gpu_pts.append({
                        'ID': item['id'],
                        'UpT': int(item['upt']),
                        'DownT': int(item['downt']),
                        'Duty': int(item['duty'])
                    })
                while len(gpu_pts) < 16:
                    last = gpu_pts[-1] if gpu_pts else {'UpT': 90, 'DownT': 85, 'Duty': 100}
                    gpu_pts.append({'ID': len(gpu_pts), 'UpT': last['UpT'], 'DownT': last['DownT'], 'Duty': last['Duty']})
                data['GPU'] = gpu_pts

                with open(p, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
    except Exception:
        pass

def save_custom_curves():
    try:
        with open(CURVE_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(active_curves, f, indent=2, ensure_ascii=False)
        sync_oem_fan_tables(active_curves)
    except Exception:
        pass

load_saved_curves()

# 共享遥测与状态数据
telemetry_data = {
    # 飞智散热底座
    "connected": False,
    "device_temp": None,
    "real_rpm": 0,
    "target_rpm": 1300,
    "mode": 0,
    "mode_name": "静音 (1300)",
    "manual_override": False,
    "manual_rpm": 1300,
    "manual_mode": 0,
    
    # 硬件遥测看板
    "cpu_temp": 45.0,
    "gpu_temp": 45.0,
    "max_temp": 45.0,
    "gpu_power_w": 0,
    "gpu_util_pct": 0,
    
    # 机械革命模式
    "mechrevo_mode": "office",
    "mechrevo_mode_name": "🍃 办公模式 (35W)",
    "mechrevo_switching": False,
    
    # 机械革命内部风扇
    "cpu_fan_rpm": 0,
    "gpu_fan_rpm": 0,
    "cpu_fan_duty": 0,
    "gpu_fan_duty": 0,
    "cpu_fan_target_duty": 0,
    "gpu_fan_target_duty": 0,
    "cpu_fan_strategy": "curve",
    "gpu_fan_strategy": "curve",
    "internal_fan_boost": False,
    
    "uptime_seconds": 0
}

# --- 1. NVML GPU 硬件遥测 ---
nvml_lib = None
gpu_handle = None

def init_nvml():
    global nvml_lib, gpu_handle
    try:
        if not nvml_lib:
            nvml_paths = glob.glob(r'C:\Windows\System32\nvml.dll') + glob.glob(r'C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll')
            if not nvml_paths:
                return False
            nvml_lib = ctypes.CDLL(nvml_paths[0])
            
        ret = nvml_lib.nvmlInit_v2()
        if ret not in (0, 9):  # 0: SUCCESS, 9: ALREADY_INITIALIZED
            nvml_lib = None
            gpu_handle = None
            return False
            
        h = ctypes.c_void_p()
        ret = nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h))
        if ret == 0:
            gpu_handle = h
            return True
        else:
            gpu_handle = None
            return False
    except Exception:
        gpu_handle = None
        return False

# 启动时初次尝试加载
init_nvml()

class NVML_UTILIZATION(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

def get_gpu_telemetry():
    global gpu_handle
    if not gpu_handle:
        if not init_nvml():
            return None, 0, 0
    try:
        temp = ctypes.c_uint()
        ret_temp = nvml_lib.nvmlDeviceGetTemperature(gpu_handle, 0, ctypes.byref(temp))
        if ret_temp != 0:
            gpu_handle = None
            return None, 0, 0

        power = ctypes.c_uint()
        ret_pwr = nvml_lib.nvmlDeviceGetPowerUsage(gpu_handle, ctypes.byref(power))
        pwr_val = round(power.value / 1000.0, 1) if ret_pwr == 0 else 0

        util = NVML_UTILIZATION()
        ret_util = nvml_lib.nvmlDeviceGetUtilizationRates(gpu_handle, ctypes.byref(util))
        util_val = int(util.gpu) if ret_util == 0 else 0

        return float(temp.value), pwr_val, util_val
    except Exception:
        gpu_handle = None
        return None, 0, 0

# --- 2. 机械革命原生 ACPI/EC 直连与风扇曲线编译引擎 ---
acpi_dll = None
ReadEC = None
WriteEC = None

try:
    if os.path.exists(ACPI_DLL_PATH):
        acpi_dll = ctypes.WinDLL(ACPI_DLL_PATH)
        ReadEC = acpi_dll.ReadEC
        ReadEC.restype = ctypes.c_ulong
        ReadEC.argtypes = [ctypes.c_ulong]
        
        WriteEC = acpi_dll.WriteEC
        WriteEC.restype = ctypes.c_ulong
        WriteEC.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
except Exception:
    acpi_dll = None

fan_mgr_instance = None
set_ec_table_method = None
set_respective_method = None
FanTable1p5_Type = None
FanTable1p5Buffer_Type = None
cpu_info_instance = None
cpu_get_temp_method = None

try:
    import clr
    import System
    from System.Reflection import Assembly, BindingFlags
    
    gcu_paths = glob.glob(r'C:\Program Files\OEM\**\GCUService.exe', recursive=True)
    if gcu_paths:
        asm = Assembly.LoadFrom(gcu_paths[0])
        FanTable1p5_Type = [t for t in asm.GetTypes() if t.Name == 'FanTable1p5'][0]
        FanTable1p5Buffer_Type = [t for t in asm.GetTypes() if t.Name == 'FanTable1p5Buffer'][0]
        mgr_type = [t for t in asm.GetTypes() if t.Name == 'FanTable_Manager1p5'][0]
        fan_mgr_instance = System.Activator.CreateInstance(mgr_type)
        
        set_ec_table_method = mgr_type.GetMethod('SetEcFanTable', BindingFlags.NonPublic | BindingFlags.Instance)
        set_respective_method = mgr_type.GetMethod('SetEcFanControlRespective', BindingFlags.NonPublic | BindingFlags.Instance)
        if set_respective_method and fan_mgr_instance:
            set_respective_method.Invoke(fan_mgr_instance, [True])

        # 初始化官方 CPUInfo 用于毫秒级实时温度采集
        try:
            cpu_info_types = [t for t in asm.GetTypes() if t.Name == 'CPUInfo']
            if cpu_info_types:
                cpu_info_instance = System.Activator.CreateInstance(cpu_info_types[0])
                cpu_get_temp_method = cpu_info_types[0].GetMethod('GetCPUTemperature')
        except Exception:
            cpu_info_instance = None
            cpu_get_temp_method = None
except Exception:
    fan_mgr_instance = None

def read_ec_telemetry():
    """从 EC 瞬时直读 CPU / GPU 风扇转速与 Duty"""
    if ReadEC:
        try:
            telemetry_data["cpu_fan_duty"] = ReadEC(0x75B) // 2
            telemetry_data["gpu_fan_duty"] = ReadEC(0x75C) // 2
            telemetry_data["cpu_fan_rpm"] = (ReadEC(0x464) << 8) | ReadEC(0x465)
            telemetry_data["gpu_fan_rpm"] = (ReadEC(0x46C) << 8) | ReadEC(0x46B)
        except Exception:
            pass

def apply_active_fan_curves(force_boost=False, target_mode=None):
    """根据选择的真实运行模式，将风扇表直接写入对应 EC 表并使能"""
    global fan_mgr_instance, set_ec_table_method, set_respective_method, FanTable1p5_Type, FanTable1p5Buffer_Type
    
    if not fan_mgr_instance or not set_ec_table_method:
        return

    try:
        import System

        # 确保双风扇独立控制使能
        if set_respective_method and fan_mgr_instance:
            try:
                set_respective_method.Invoke(fan_mgr_instance, [True])
            except Exception:
                pass

        ft = System.Activator.CreateInstance(FanTable1p5_Type)
        ft.Activated = True
        ft.FanControlRespective = True
        ft.CpuTemp_DefaultMaxLevel = 14
        ft.GpuTemp_DefaultMaxLevel = 14

        cpu_list = []
        for i, item in enumerate(active_curves["cpu"][:16]):
            buf = System.Activator.CreateInstance(FanTable1p5Buffer_Type)
            buf.ID = System.UInt32(i)
            buf.UpT = System.Byte(int(item["upt"]))
            buf.DownT = System.Byte(int(item["downt"]))
            duty_val = 100 if force_boost else min(100, max(0, int(item["duty"])))
            buf.Duty = System.Byte(duty_val)
            cpu_list.append(buf)

        gpu_list = []
        for i, item in enumerate(active_curves["gpu"][:16]):
            buf = System.Activator.CreateInstance(FanTable1p5Buffer_Type)
            buf.ID = System.UInt32(i)
            buf.UpT = System.Byte(int(item["upt"]))
            buf.DownT = System.Byte(int(item["downt"]))
            duty_val = 100 if force_boost else min(100, max(0, int(item["duty"])))
            buf.Duty = System.Byte(duty_val)
            gpu_list.append(buf)

        cpu_arr = System.Array.CreateInstance(FanTable1p5Buffer_Type, len(cpu_list))
        for i, b in enumerate(cpu_list): cpu_arr.SetValue(b, i)
        gpu_arr = System.Array.CreateInstance(FanTable1p5Buffer_Type, len(gpu_list))
        for i, b in enumerate(gpu_list): gpu_arr.SetValue(b, i)

        ft.CPU = cpu_arr
        ft.GPU = gpu_arr

        # 精准写入当前激活模式的温控表 (Office=M1T1, Gaming=M2T1, Turbo=M3T1)，绝不篡改主板模式
        cur_mode = target_mode or telemetry_data.get("mechrevo_mode", "office")
        table_map = {
            "office": "M1T1",
            "gaming": "M2T1",
            "turbo": "M3T1"
        }
        mode_table = table_map.get(cur_mode, "M1T1")
        ft.Name = mode_table
        set_ec_table_method.Invoke(fan_mgr_instance, [ft])
    except Exception:
        pass

def get_cpu_temp():
    # 1. 优先使用机械革命原生 GCUService.CPUInfo 采集实时温度 (灵敏响应，无 ACPI 静态假死)
    if cpu_get_temp_method and cpu_info_instance:
        try:
            val = cpu_get_temp_method.Invoke(cpu_info_instance, [])
            if val is not None and 25 <= float(val) <= 115:
                return round(float(val), 1)
        except Exception:
            pass

    # 2. 兜底回退 root\wmi MSAcpi_ThermalZoneTemperature
    try:
        w_acpi = wmi.WMI(namespace="root\\wmi")
        for t in w_acpi.MSAcpi_ThermalZoneTemperature():
            temp = (t.CurrentTemperature / 10.0) - 273.15
            if 25 <= temp <= 115:
                return round(temp, 1)
    except Exception:
        pass
    return None

def get_hardware_temp():
    gpu_t, gpu_pwr, gpu_util = get_gpu_telemetry()
    telemetry_data["gpu_power_w"] = gpu_pwr
    telemetry_data["gpu_util_pct"] = gpu_util
    
    cpu_t = get_cpu_temp()
    read_ec_telemetry()

    if gpu_t is None:
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == u'Temperature' and u'GPU Core' in s.Name:
                    if s.Value and s.Value > 20:
                        gpu_t = float(s.Value)
                        break
        except:
            pass

    if gpu_t is None: gpu_t = cpu_t or 45.0
    if cpu_t is None: cpu_t = gpu_t

    return cpu_t, gpu_t

def read_mechrevo_status():
    try:
        paths = glob.glob(r'C:\Program Files\OEM\**\MainOption.json', recursive=True)
        if paths:
            with open(paths[0], 'r', encoding='utf-8') as f:
                data = json.load(f)
                op_mode = data.get('OperatingMode', 0)
                if op_mode == 0:
                    telemetry_data["mechrevo_mode"] = "office"
                    telemetry_data["mechrevo_mode_name"] = "🍃 办公模式 (35W)"
                elif op_mode == 1:
                    telemetry_data["mechrevo_mode"] = "gaming"
                    telemetry_data["mechrevo_mode_name"] = "🎮 游戏模式 (50W)"
                elif op_mode == 2:
                    telemetry_data["mechrevo_mode"] = "turbo"
                    telemetry_data["mechrevo_mode_name"] = "⚡ 狂暴模式 (95W)"
    except Exception:
        pass

def switch_mechrevo_mode_async(target_mode):
    def _worker():
        telemetry_data["mechrevo_switching"] = True
        mode_map = {
            "office": "OPERATING_OFFICE_MODE",
            "gaming": "OPERATING_GAMING_MODE",
            "turbo": "OPERATING_TURBO_MODE"
        }
        cmd_param = mode_map.get(target_mode, "OPERATING_OFFICE_MODE")
        try:
            # 1. 同步更新底层 MainOption.json 中的真实运行模式，防止轮询被动覆盖
            paths = glob.glob(r'C:\Program Files\OEM\**\MainOption.json', recursive=True)
            if paths:
                mode_int = {"office": 0, "gaming": 1, "turbo": 2}.get(target_mode, 0)
                try:
                    with open(paths[0], 'r', encoding='utf-8') as f:
                        mo = json.load(f)
                    mo["OperatingMode"] = mode_int
                    with open(paths[0], 'w', encoding='utf-8') as f:
                        json.dump(mo, f, indent=2)
                except Exception:
                    pass

            # 2. 调用当前真实模式对应的风扇表
            apply_active_fan_curves(force_boost=telemetry_data.get("internal_fan_boost", False), target_mode=target_mode)

            # 3. 异步尝试调用官方切换管道
            subprocess.run(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', SWITCH_SCRIPT_PATH, '-cmd', cmd_param],
                capture_output=True,
                text=True,
                timeout=15
            )
            telemetry_data["mechrevo_mode"] = target_mode
            if target_mode == "office":
                telemetry_data["mechrevo_mode_name"] = "🍃 办公模式 (35W)"
            elif target_mode == "gaming":
                telemetry_data["mechrevo_mode_name"] = "🎮 游戏模式 (50W)"
            elif target_mode == "turbo":
                telemetry_data["mechrevo_mode_name"] = "⚡ 狂暴模式 (95W)"
        except Exception:
            pass
        finally:
            telemetry_data["mechrevo_switching"] = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐾 机械革命 & 飞智智能控制中枢</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>❄️</text></svg>">
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.75);
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.35);
            --accent: #818cf8;
            --success: #34d399;
            --warning: #fbbf24;
            --danger: #f87171;
            --overdrive: #f43f5e;
            --text: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background: radial-gradient(circle at 50% 10%, #1e293b 0%, #0f172a 100%);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 24px 16px;
        }

        .container {
            width: 100%;
            max-width: 640px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 4px 8px;
        }

        .header h1 {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(135deg, #38bdf8, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .badge {
            font-size: 0.75rem;
            padding: 4px 10px;
            border-radius: 9999px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .badge.online {
            background: rgba(52, 211, 153, 0.15);
            color: var(--success);
            border: 1px solid rgba(52, 211, 153, 0.3);
        }

        .badge.offline {
            background: rgba(248, 113, 113, 0.15);
            color: var(--danger);
            border: 1px solid rgba(248, 113, 113, 0.3);
        }

        .dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background-color: currentColor;
            box-shadow: 0 0 8px currentColor;
        }

        .card {
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
        }

        .card-title {
            font-size: 0.84rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        /* 硬件实时遥测看板 */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
        }

        .stat-item {
            display: flex;
            flex-direction: column;
            background: rgba(15, 23, 42, 0.5);
            padding: 10px 8px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            text-align: center;
        }

        .stat-label {
            font-size: 0.68rem;
            color: var(--text-muted);
            margin-bottom: 3px;
        }

        .stat-value {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--primary);
            font-variant-numeric: tabular-nums;
        }

        .stat-value.cpu-color { color: #f59e0b; }
        .stat-value.gpu-color { color: #38bdf8; }
        .stat-value.pwr-color { color: #ec4899; }
        .stat-value.util-color { color: #34d399; }

        .stat-unit {
            font-size: 0.68rem;
            font-weight: 400;
            color: var(--text-muted);
            margin-left: 2px;
        }

        /* 性能模式 */
        .mechrevo-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }

        .mechrevo-btn {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 12px 8px;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            color: var(--text);
            text-align: center;
        }

        .mechrevo-btn .icon { font-size: 1.4rem; margin-bottom: 2px; }
        .mechrevo-btn .name { font-size: 0.85rem; font-weight: 600; }
        .mechrevo-btn .desc { font-size: 0.68rem; color: var(--text-muted); }

        .mechrevo-btn:hover { border-color: rgba(255, 255, 255, 0.2); transform: translateY(-2px); }
        .mechrevo-btn.active-office {
            background: rgba(52, 211, 153, 0.15); border-color: var(--success); color: var(--success);
            box-shadow: 0 0 15px rgba(52, 211, 153, 0.25);
        }
        .mechrevo-btn.active-gaming {
            background: rgba(56, 189, 248, 0.15); border-color: var(--primary); color: var(--primary);
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.25);
        }
        .mechrevo-btn.active-turbo {
            background: rgba(244, 63, 94, 0.18); border-color: var(--overdrive); color: var(--overdrive);
            box-shadow: 0 0 18px rgba(244, 63, 94, 0.35);
        }

        /* 风扇卡片 */
        .fan-status-banner {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 12px;
        }

        .fan-channel-badge {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 10px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .fan-channel-badge .title {
            font-size: 0.82rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .fan-channel-badge .rpm {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--primary);
            font-variant-numeric: tabular-nums;
        }

        /* 曲线编辑器 */
        .tab-bar {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
        }

        .tab-btn {
            flex: 1;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 8px;
            color: var(--text-muted);
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }

        .tab-btn.active-cpu {
            background: rgba(245, 158, 11, 0.2);
            color: #fbbf24;
            border-color: #f59e0b;
        }

        .tab-btn.active-gpu {
            background: rgba(56, 189, 248, 0.2);
            color: #38bdf8;
            border-color: #38bdf8;
        }

        .canvas-container {
            background: #090d16;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 12px;
            position: relative;
            margin-bottom: 14px;
        }

        canvas {
            width: 100%;
            height: 200px;
            display: block;
            cursor: crosshair;
        }

        /* 点位微调表格 */
        .points-table-wrapper {
            max-height: 190px;
            overflow-y: auto;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            background: rgba(15, 23, 42, 0.4);
            margin-bottom: 14px;
        }

        .points-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.75rem;
            text-align: center;
        }

        .points-table th {
            background: rgba(30, 41, 59, 0.8);
            padding: 6px 4px;
            color: var(--text-muted);
            position: sticky;
            top: 0;
            z-index: 1;
        }

        .points-table td {
            padding: 5px 4px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
        }

        .point-input {
            width: 52px;
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 6px;
            color: var(--text);
            text-align: center;
            font-size: 0.75rem;
            padding: 3px 2px;
        }

        .point-input:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 6px var(--primary-glow);
        }

        /* 预设与操作按扭 */
        .action-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin-bottom: 10px;
        }

        .action-btn {
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 8px 4px;
            font-size: 0.72rem;
            font-weight: 600;
            color: var(--text);
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }

        .action-btn:hover {
            border-color: var(--primary);
            transform: translateY(-1px);
        }

        .action-btn.save {
            grid-column: span 2;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            border-color: #38bdf8;
            color: #ffffff;
            font-weight: 700;
        }

        .action-btn.save:hover {
            box-shadow: 0 0 15px var(--primary-glow);
        }

        .boost-all-btn {
            width: 100%;
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.25), rgba(236, 72, 153, 0.25));
            border: 1px solid rgba(244, 63, 94, 0.5);
            border-radius: 10px;
            padding: 10px;
            color: #ffffff;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .boost-all-btn:hover {
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.4), rgba(236, 72, 153, 0.4));
            box-shadow: 0 0 15px rgba(244, 63, 94, 0.4);
        }

        .boost-all-btn.active {
            background: var(--overdrive);
            border-color: var(--overdrive);
            box-shadow: 0 0 20px rgba(244, 63, 94, 0.6);
        }

        /* 飞智散热转速仪表盘 */
        .gauge-section {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 12px 0;
            position: relative;
        }

        .rpm-display {
            font-size: 2.5rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            background: linear-gradient(180deg, #ffffff 0%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: baseline;
            gap: 4px;
        }

        .rpm-unit {
            font-size: 0.95rem;
            font-weight: 500;
            color: var(--text-muted);
            -webkit-text-fill-color: var(--text-muted);
        }

        .status-pill {
            margin-top: 6px;
            font-size: 0.82rem;
            color: var(--primary);
            background: rgba(56, 189, 248, 0.1);
            padding: 4px 14px;
            border-radius: 9999px;
            border: 1px solid rgba(56, 189, 248, 0.2);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* 档位矩阵 */
        .grid-buttons {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-top: 14px;
        }

        .btn {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 10px 8px;
            color: var(--text);
            font-size: 0.82rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
        }

        .btn .btn-sub {
            font-size: 0.68rem;
            font-weight: 400;
            color: var(--text-muted);
        }

        .btn:hover {
            border-color: rgba(255, 255, 255, 0.2);
            background: rgba(30, 41, 59, 0.8);
            transform: translateY(-2px);
        }

        .btn.active {
            background: var(--primary);
            color: #0f172a;
            border-color: var(--primary);
            box-shadow: 0 0 15px var(--primary-glow);
        }

        .btn.active .btn-sub { color: rgba(15, 23, 42, 0.75); }

        .btn.overdrive:hover {
            border-color: rgba(244, 63, 94, 0.4);
            box-shadow: 0 0 10px rgba(244, 63, 94, 0.2);
        }

        .btn.overdrive.active {
            background: var(--overdrive);
            color: #ffffff;
            border-color: var(--overdrive);
            box-shadow: 0 0 15px rgba(244, 63, 94, 0.4);
        }

        .btn.overdrive.active .btn-sub { color: rgba(255, 255, 255, 0.8); }

        .btn-full { grid-column: span 3; }

        /* 无级滑块 */
        .slider-box {
            margin-top: 14px;
            background: rgba(15, 23, 42, 0.5);
            padding: 12px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .slider-header {
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .slider-header .val {
            font-weight: 700;
            color: var(--primary);
        }

        input[type="range"] {
            -webkit-appearance: none;
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: rgba(255, 255, 255, 0.1);
            outline: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--primary);
            cursor: pointer;
            box-shadow: 0 0 10px var(--primary-glow);
            transition: transform 0.1s;
        }

        input[type="range"]::-webkit-slider-thumb:hover { transform: scale(1.2); }

        .footer {
            text-align: center;
            font-size: 0.72rem;
            color: var(--text-muted);
            margin-top: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- 顶栏状态 -->
        <div class="header">
            <h1>🐾 机械革命 & 飞智智能控制中枢</h1>
            <div id="conn-badge" class="badge offline">
                <span class="dot"></span>
                <span id="conn-text">检测中...</span>
            </div>
        </div>

        <!-- 1. 硬件实时遥测看板 -->
        <div class="card">
            <div class="card-title">
                <span>🌡️ 硬件实时遥测 (独立温度与功耗)</span>
                <span id="ctrl-strategy" style="color: var(--primary);">🤖 智能温控</span>
            </div>
            <div class="stats-grid">
                <div class="stat-item">
                    <span class="stat-label">CPU 核心温度</span>
                    <span class="stat-value cpu-color"><span id="cpu-temp">--</span><span class="stat-unit">°C</span></span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">GPU 核心温度</span>
                    <span class="stat-value gpu-color"><span id="gpu-temp">--</span><span class="stat-unit">°C</span></span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">GPU 实时功耗</span>
                    <span class="stat-value pwr-color"><span id="gpu-pwr">--</span><span class="stat-unit">W</span></span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">GPU 核心负载</span>
                    <span class="stat-value util-color"><span id="gpu-util">--</span><span class="stat-unit">%</span></span>
                </div>
            </div>
        </div>

        <!-- 2. 机械革命性能模式切换 -->
        <div class="card">
            <div class="card-title">
                <span>⚡ 机械革命功耗模式切换</span>
                <span id="mr-mode-badge" style="color: var(--success);">🍃 办公模式</span>
            </div>
            <div class="mechrevo-grid">
                <div id="mr-office" class="mechrevo-btn active-office" onclick="setMechrevoMode('office')">
                    <span class="icon">🍃</span>
                    <span class="name">办公模式</span>
                    <span class="desc">35W 极静节能</span>
                </div>
                <div id="mr-gaming" class="mechrevo-btn" onclick="setMechrevoMode('gaming')">
                    <span class="icon">🎮</span>
                    <span class="name">游戏模式</span>
                    <span class="desc">50W 均衡输出</span>
                </div>
                <div id="mr-turbo" class="mechrevo-btn" onclick="setMechrevoMode('turbo')">
                    <span class="icon">⚡</span>
                    <span class="name">狂暴模式</span>
                    <span class="desc">95W 极致性能</span>
                </div>
            </div>
        </div>

        <!-- 3. 机械革命笔记本内部风扇可视化曲线编辑器 (支持 14 点温度/占空比直接拖拽编辑与填写) -->
        <div class="card">
            <div class="card-title">
                <span>📈 笔记本内部风扇 EC 硬件级温控曲线编辑器</span>
                <span id="curve-status" style="font-size: 0.72rem; color: #34d399;">已加载自定义曲线</span>
            </div>

            <div class="fan-status-banner">
                <div class="fan-channel-badge">
                    <span class="title">🔥 CPU 风扇</span>
                    <span class="rpm"><span id="cpu-fan-rpm">--</span> RPM (<span id="cpu-fan-duty">--</span>%)</span>
                </div>
                <div class="fan-channel-badge">
                    <span class="title">🎮 GPU 风扇</span>
                    <span class="rpm"><span id="gpu-fan-rpm">--</span> RPM (<span id="gpu-fan-duty">--</span>%)</span>
                </div>
            </div>

            <!-- 选项卡 -->
            <div class="tab-bar">
                <div id="tab-cpu" class="tab-btn active-cpu" onclick="selectCurveTab('cpu')">🔥 CPU 温控曲线 (14点)</div>
                <div id="tab-gpu" class="tab-btn" onclick="selectCurveTab('gpu')">🎮 GPU 温控曲线 (14点)</div>
            </div>

            <!-- 可视化折线图 -->
            <div class="canvas-container">
                <canvas id="curve-canvas" width="600" height="220"></canvas>
            </div>

            <!-- 14 点位表格明细直接编辑 -->
            <div class="points-table-wrapper">
                <table class="points-table">
                    <thead>
                        <tr>
                            <th>点位</th>
                            <th>起转温度 (°C)</th>
                            <th>回落温度 (°C)</th>
                            <th>风扇占空比 (%)</th>
                        </tr>
                    </thead>
                    <tbody id="points-tbody">
                        <!-- 由 JS 渲染 -->
                    </tbody>
                </table>
            </div>

            <!-- 预设与保存操作栏 -->
            <div class="action-row">
                <button class="action-btn" onclick="applyPreset('zero')">🛑 0 RPM 静音预设</button>
                <button class="action-btn" onclick="applyPreset('balanced')">🍃 日常均衡预设</button>
                <button class="action-btn" onclick="applyPreset('gaming')">❄️ 电竞激进预设</button>
                <button class="action-btn" onclick="reloadCurves()">🔄 恢复默认</button>
                <button class="action-btn save" onclick="saveAndApplyCurves()">💾 保存并立即写入 EC 硬件生效</button>
            </div>

            <!-- 全局一键强冷 -->
            <button id="btn-boost-all" class="boost-all-btn" onclick="toggleGlobalBoost()">
                ⚡ 双风扇全局一键强冷 (100% 满速排热)
            </button>
        </div>

        <!-- 4. 飞智外置智能半导体散热底座 -->
        <div class="card">
            <div class="card-title">
                <span>❄️ 飞智 BS2PRO 散热底座</span>
                <span id="mode-pill" class="status-pill">静音自适应</span>
            </div>

            <div class="gauge-section">
                <div class="rpm-display">
                    <span id="real-rpm">----</span>
                    <span class="rpm-unit">RPM</span>
                </div>
            </div>

            <!-- 飞智快捷档位矩阵 -->
            <div class="grid-buttons">
                <button id="btn-auto" class="btn active btn-full" onclick="setAuto()">
                    <span>🤖 智能自适应温控 (推荐)</span>
                    <span class="btn-sub">根据 CPU & GPU 最高温平滑无感调速</span>
                </button>
                <button class="btn" onclick="setSpeed(0, 1000)">
                    <span>微风</span>
                    <span class="btn-sub">1000 RPM</span>
                </button>
                <button class="btn" onclick="setSpeed(0, 1300)">
                    <span>静音</span>
                    <span class="btn-sub">1300 RPM</span>
                </button>
                <button class="btn" onclick="setSpeed(0, 1700)">
                    <span>柔风</span>
                    <span class="btn-sub">1700 RPM</span>
                </button>
                <button class="btn" onclick="setSpeed(1, 2100)">
                    <span>均衡</span>
                    <span class="btn-sub">2100 RPM</span>
                </button>
                <button class="btn" onclick="setSpeed(1, 2600)">
                    <span>强效</span>
                    <span class="btn-sub">2600 RPM</span>
                </button>
                <button class="btn overdrive" onclick="setSpeed(1, 3000)">
                    <span>疾风</span>
                    <span class="btn-sub">3000 RPM</span>
                </button>
                <button class="btn overdrive" onclick="setSpeed(1, 3500)">
                    <span>超频</span>
                    <span class="btn-sub">3500 RPM</span>
                </button>
                <button class="btn overdrive" onclick="setSpeed(1, 4000)">
                    <span>⚡ 狂暴上限</span>
                    <span class="btn-sub">4000 RPM</span>
                </button>
            </div>

            <!-- 底座无级滑块 -->
            <div class="slider-box">
                <div class="slider-header">
                    <span>⚡ 底座转速无级微调 (800 - 4000 RPM)</span>
                    <span id="slider-val" class="val">1300 RPM</span>
                </div>
                <input type="range" id="rpm-slider" min="800" max="4000" step="50" value="1300" oninput="onSliderChange(this.value)" onchange="onSliderCommit(this.value)">
            </div>
        </div>

        <div class="footer">
            🐾 机械革命 & 飞智守护进程 · 纯轻量原生架构 · 待机免崩溃
        </div>
    </div>

    <script>
        let isSlidingFly = false;
        let isGlobalBoost = false;
        let currentTab = 'cpu';
        let curvesData = { cpu: [], gpu: [] };
        let latestTelemetry = { cpu_temp: 45, gpu_temp: 45 };

        let canvas = document.getElementById('curve-canvas');
        let ctx = canvas.getContext('2d');
        let draggingPointIdx = null;

        function selectCurveTab(tab) {
            currentTab = tab;
            document.getElementById('tab-cpu').className = 'tab-btn' + (tab === 'cpu' ? ' active-cpu' : '');
            document.getElementById('tab-gpu').className = 'tab-btn' + (tab === 'gpu' ? ' active-gpu' : '');
            renderTable();
            drawCanvas();
        }

        function renderTable() {
            const list = curvesData[currentTab] || [];
            const tbody = document.getElementById('points-tbody');
            tbody.innerHTML = '';
            list.forEach((p, idx) => {
                if (idx >= 14) return;
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>#${p.id + 1}</td>
                    <td><input type="number" class="point-input" value="${p.upt}" min="30" max="100" onchange="onPointEdit(${idx}, 'upt', this.value)"></td>
                    <td><input type="number" class="point-input" value="${p.downt}" min="25" max="98" onchange="onPointEdit(${idx}, 'downt', this.value)"></td>
                    <td><input type="number" class="point-input" value="${p.duty}" min="0" max="100" onchange="onPointEdit(${idx}, 'duty', this.value)"></td>
                `;
                tbody.appendChild(tr);
            });
        }

        function onPointEdit(idx, field, val) {
            val = parseInt(val) || 0;
            if (field === 'duty') val = Math.max(0, Math.min(100, val));
            if (field === 'upt') val = Math.max(30, Math.min(100, val));
            if (field === 'downt') val = Math.max(25, Math.min(98, val));
            curvesData[currentTab][idx][field] = val;
            drawCanvas();
        }

        // 画布坐标映射
        const PADDING_L = 35;
        const PADDING_R = 15;
        const PADDING_T = 15;
        const PADDING_B = 25;
        const MIN_TEMP = 35;
        const MAX_TEMP = 100;

        function tempToX(temp, w) {
            return PADDING_L + ((temp - MIN_TEMP) / (MAX_TEMP - MIN_TEMP)) * (w - PADDING_L - PADDING_R);
        }
        function xToTemp(x, w) {
            return MIN_TEMP + ((x - PADDING_L) / (w - PADDING_L - PADDING_R)) * (MAX_TEMP - MIN_TEMP);
        }
        function dutyToY(duty, h) {
            return h - PADDING_B - (duty / 100) * (h - PADDING_T - PADDING_B);
        }
        function yToDuty(y, h) {
            return Math.round((h - PADDING_B - y) / (h - PADDING_T - PADDING_B) * 100);
        }

        function drawCanvas() {
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            // 背景网格与轴线
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
            ctx.lineWidth = 1;
            for (let t = 40; t <= 100; t += 10) {
                const x = tempToX(t, w);
                ctx.beginPath();
                ctx.moveTo(x, PADDING_T);
                ctx.lineTo(x, h - PADDING_B);
                ctx.stroke();

                ctx.fillStyle = '#64748b';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(t + '°', x, h - 8);
            }

            for (let d = 0; d <= 100; d += 25) {
                const y = dutyToY(d, h);
                ctx.beginPath();
                ctx.moveTo(PADDING_L, y);
                ctx.lineTo(w - PADDING_R, y);
                ctx.stroke();

                ctx.fillStyle = '#64748b';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'right';
                ctx.fillText(d + '%', PADDING_L - 6, y + 3);
            }

            const points = (curvesData[currentTab] || []).slice(0, 14);
            if (!points.length) return;

            // 绘制当前实际硬件温度坚线指示
            const liveTemp = currentTab === 'cpu' ? latestTelemetry.cpu_temp : latestTelemetry.gpu_temp;
            if (liveTemp) {
                const liveX = tempToX(Math.min(100, Math.max(35, liveTemp)), w);
                ctx.strokeStyle = currentTab === 'cpu' ? 'rgba(245, 158, 11, 0.6)' : 'rgba(56, 189, 248, 0.6)';
                ctx.lineWidth = 2;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(liveX, PADDING_T);
                ctx.lineTo(liveX, h - PADDING_B);
                ctx.stroke();
                ctx.setLineDash([]);

                ctx.fillStyle = currentTab === 'cpu' ? '#f59e0b' : '#38bdf8';
                ctx.font = 'bold 10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(Math.round(liveTemp) + '°C 实时', liveX, PADDING_T + 12);
            }

            // 绘制温控折线
            const mainColor = currentTab === 'cpu' ? '#f59e0b' : '#38bdf8';
            ctx.strokeStyle = mainColor;
            ctx.lineWidth = 2.5;
            ctx.beginPath();

            points.forEach((p, idx) => {
                const x = tempToX(p.upt, w);
                const y = dutyToY(p.duty, h);
                if (idx === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // 绘制点位圆点
            points.forEach((p, idx) => {
                const x = tempToX(p.upt, w);
                const y = dutyToY(p.duty, h);
                ctx.fillStyle = idx === draggingPointIdx ? '#ffffff' : mainColor;
                ctx.beginPath();
                ctx.arc(x, y, idx === draggingPointIdx ? 6 : 4.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#0f172a';
                ctx.lineWidth = 1.5;
                ctx.stroke();
            });
        }

        // 交互拖拽控制点
        canvas.addEventListener('mousedown', (e) => {
            const rect = canvas.getBoundingClientRect();
            const mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
            const mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);
            const points = (curvesData[currentTab] || []).slice(0, 14);

            for (let i = 0; i < points.length; i++) {
                const px = tempToX(points[i].upt, canvas.width);
                const py = dutyToY(points[i].duty, canvas.height);
                if (Math.hypot(mouseX - px, mouseY - py) < 12) {
                    draggingPointIdx = i;
                    drawCanvas();
                    break;
                }
            }
        });

        window.addEventListener('mousemove', (e) => {
            if (draggingPointIdx === null) return;
            const rect = canvas.getBoundingClientRect();
            const mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
            const mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);

            let newTemp = Math.round(xToTemp(mouseX, canvas.width));
            let newDuty = Math.round(yToDuty(mouseY, canvas.height));
            newTemp = Math.max(35, Math.min(100, newTemp));
            newDuty = Math.max(0, Math.min(100, newDuty));

            const pts = curvesData[currentTab];
            pts[draggingPointIdx].upt = newTemp;
            pts[draggingPointIdx].downt = Math.max(25, newTemp - 6);
            pts[draggingPointIdx].duty = newDuty;

            renderTable();
            drawCanvas();
        });

        window.addEventListener('mouseup', () => {
            if (draggingPointIdx !== null) {
                draggingPointIdx = null;
                drawCanvas();
            }
        });

        // 预设模版
        function applyPreset(type) {
            const pts = curvesData[currentTab];
            if (type === 'zero') {
                // 0 RPM 静音停转曲线：80°C 以下均为 0% 停转，85°C 启动保护
                pts.forEach((p, i) => {
                    if (p.upt <= 82) p.duty = 0;
                    else if (p.upt <= 88) p.duty = 45;
                    else if (p.upt <= 93) p.duty = 75;
                    else p.duty = 100;
                });
            } else if (type === 'balanced') {
                // 日常均衡：55°C 以下 0%，之后平缓爬升
                pts.forEach((p, i) => {
                    if (p.upt <= 54) p.duty = 0;
                    else if (p.upt <= 65) p.duty = 30;
                    else if (p.upt <= 75) p.duty = 45;
                    else if (p.upt <= 85) p.duty = 65;
                    else p.duty = 95;
                });
            } else if (type === 'gaming') {
                // 电竞激进：全程高风量
                pts.forEach((p, i) => {
                    if (p.upt <= 50) p.duty = 35;
                    else if (p.upt <= 65) p.duty = 55;
                    else if (p.upt <= 75) p.duty = 75;
                    else p.duty = 100;
                });
            }
            renderTable();
            drawCanvas();
        }

        async function loadCurves() {
            try {
                const res = await fetch('/api/mechrevo/fantable');
                if (res.ok) {
                    curvesData = await res.json();
                    renderTable();
                    drawCanvas();
                }
            } catch (e) {}
        }

        async function reloadCurves() {
            await loadCurves();
        }

        async function saveAndApplyCurves() {
            const statusEl = document.getElementById('curve-status');
            statusEl.innerText = '正在写入 EC 硬件...';
            statusEl.style.color = '#fbbf24';

            try {
                const res = await fetch('/api/mechrevo/fantable/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(curvesData)
                });
                if (res.ok) {
                    statusEl.innerText = '✅ EC 写入成功并已即时生效！';
                    statusEl.style.color = '#34d399';
                    setTimeout(() => {
                        statusEl.innerText = '已加载自定义曲线';
                    }, 3000);
                }
            } catch (e) {
                statusEl.innerText = '❌ 写入失败';
                statusEl.style.color = '#f87171';
            }
            fetchStatus();
        }

        function updateUI(data) {
            latestTelemetry = data;

            // 散热底座状态
            const badge = document.getElementById('conn-badge');
            const connText = document.getElementById('conn-text');
            if (data.connected) {
                badge.className = 'badge online';
                connText.innerText = '散热底座已连接 (飞智 BS2)';
            } else {
                badge.className = 'badge offline';
                connText.innerText = '散热底座断开';
            }

            // 硬件遥测看板
            document.getElementById('cpu-temp').innerText = Math.round(data.cpu_temp);
            document.getElementById('gpu-temp').innerText = Math.round(data.gpu_temp);
            document.getElementById('gpu-pwr').innerText = data.gpu_power_w || '--';
            document.getElementById('gpu-util').innerText = data.gpu_util_pct || '0';

            // 机械革命功耗模式
            const mrBadge = document.getElementById('mr-mode-badge');
            mrBadge.innerText = data.mechrevo_mode_name || '办公模式';
            
            document.getElementById('mr-office').className = 'mechrevo-btn' + (data.mechrevo_mode === 'office' ? ' active-office' : '');
            document.getElementById('mr-gaming').className = 'mechrevo-btn' + (data.mechrevo_mode === 'gaming' ? ' active-gaming' : '');
            document.getElementById('mr-turbo').className = 'mechrevo-btn' + (data.mechrevo_mode === 'turbo' ? ' active-turbo' : '');

            // 机械革命本体风扇转速与 Duty
            document.getElementById('cpu-fan-rpm').innerText = data.cpu_fan_rpm !== undefined ? data.cpu_fan_rpm : '--';
            document.getElementById('gpu-fan-rpm').innerText = data.gpu_fan_rpm !== undefined ? data.gpu_fan_rpm : '--';
            document.getElementById('cpu-fan-duty').innerText = data.cpu_fan_duty !== undefined ? data.cpu_fan_duty : '--';
            document.getElementById('gpu-fan-duty').innerText = data.gpu_fan_duty !== undefined ? data.gpu_fan_duty : '--';

            // 全局强冷按钮
            isGlobalBoost = !!data.internal_fan_boost;
            const boostBtn = document.getElementById('btn-boost-all');
            boostBtn.className = 'boost-all-btn' + (isGlobalBoost ? ' active' : '');
            boostBtn.innerHTML = isGlobalBoost ? '🔥 强冷全开中 (双风扇 100% 满速) - 点击关闭' : '⚡ 双风扇全局一键强冷 (100% 满速排热)';

            // 飞智底座风扇转速
            document.getElementById('real-rpm').innerText = data.real_rpm || data.target_rpm || '----';
            document.getElementById('mode-pill').innerText = data.mode_name + (data.manual_override ? ' [手动定速]' : ' [智能自适应]');
            document.getElementById('ctrl-strategy').innerText = data.manual_override ? '⚙️ 手动模式' : '🤖 智能温控';

            if (!isSlidingFly && data.target_rpm) {
                document.getElementById('rpm-slider').value = data.target_rpm;
                document.getElementById('slider-val').innerText = data.target_rpm + ' RPM';
            }

            const autoBtn = document.getElementById('btn-auto');
            if (!data.manual_override) {
                autoBtn.className = 'btn active';
            } else {
                autoBtn.className = 'btn';
            }

            drawCanvas();
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (res.ok) {
                    const data = await res.json();
                    updateUI(data);
                }
            } catch (e) {}
        }

        async function setMechrevoMode(mode) {
            document.getElementById('mr-mode-badge').innerText = '切换中...';
            await fetch('/api/mechrevo/set?mode=' + mode);
            setTimeout(fetchStatus, 800);
        }

        async function toggleGlobalBoost() {
            const target = isGlobalBoost ? 'off' : 'on';
            await fetch('/api/mechrevo/fan/boost?state=' + target);
            setTimeout(fetchStatus, 300);
        }

        async function setSpeed(mode, rpm) {
            await fetch('/api/set?mode=' + mode + '&rpm=' + rpm);
            fetchStatus();
        }

        async function setAuto() {
            await fetch('/api/auto');
            fetchStatus();
        }

        function onSliderChange(val) {
            isSlidingFly = true;
            document.getElementById('slider-val').innerText = val + ' RPM';
        }

        async function onSliderCommit(val) {
            isSlidingFly = false;
            const rpm = parseInt(val);
            const mode = rpm >= 2200 ? 1 : 0;
            await setSpeed(mode, rpm);
        }

        loadCurves();
        setInterval(fetchStatus, 1500);
        fetchStatus();
    </script>
</body>
</html>
"""

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path.startswith('/index'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
        elif self.path.startswith('/api/status'):
            telemetry_data["uptime_seconds"] = int(time.time() - start_time)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(telemetry_data).encode('utf-8'))
        elif self.path.startswith('/api/mechrevo/fantable'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(active_curves).encode('utf-8'))
        elif self.path.startswith('/api/mechrevo/set'):
            try:
                qs = parse_qs(urlparse(self.path).query)
                mode = qs.get('mode', ['office'])[0]
                switch_mechrevo_mode_async(mode)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception:
                self.send_response(500)
                self.end_headers()
        elif self.path.startswith('/api/mechrevo/fan/boost'):
            try:
                qs = parse_qs(urlparse(self.path).query)
                state = qs.get('state', ['on'])[0]
                is_boost = (state == 'on')
                telemetry_data["internal_fan_boost"] = is_boost
                apply_active_fan_curves(force_boost=is_boost)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception:
                self.send_response(500)
                self.end_headers()
        elif self.path.startswith('/api/set'):
            try:
                qs = parse_qs(urlparse(self.path).query)
                mode = int(qs.get('mode', [0])[0])
                rpm = int(qs.get('rpm', [1300])[0])
                rpm = max(800, min(4000, rpm))
                telemetry_data["manual_override"] = True
                telemetry_data["manual_mode"] = mode
                telemetry_data["manual_rpm"] = rpm
                telemetry_data["mode_name"] = f"手动 ({rpm} RPM)"
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception:
                self.send_response(500)
                self.end_headers()
        elif self.path.startswith('/api/auto'):
            telemetry_data["manual_override"] = False
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith('/api/mechrevo/fantable/save'):
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_len).decode('utf-8')
                new_data = json.loads(body)
                if "cpu" in new_data and "gpu" in new_data:
                    active_curves["cpu"] = new_data["cpu"]
                    active_curves["gpu"] = new_data["gpu"]
                    save_custom_curves()
                    apply_active_fan_curves(force_boost=False)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                    return
                self.send_response(400)
                self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(('0.0.0.0', WEB_PORT), WebHandler)
    server.serve_forever()

class FlydigiController:
    def __init__(self):
        self.all_interfaces = []
        self.last_mode = -1
        self.last_rpm = -1
        self.first_run = True
        
    def _input_handler(self, data):
        try:
            if len(data) > 10 and data[1] == 0x5A and data[2] == 0xA5:
                cmd = data[3]
                if cmd == 0xEF:
                    # bytes 8 and 9 are real RPM (low byte + high byte)
                    rpm_low = data[8]
                    rpm_high = data[9]
                    telemetry_data["real_rpm"] = rpm_low + (rpm_high << 8)
        except:
            pass
            
    def connect(self):
        try:
            filter = hid.HidDeviceFilter(vendor_id=DEVICE_VID, product_id=DEVICE_PID)
            devices = filter.get_devices()
            if devices:
                self.all_interfaces = devices
                for dev in self.all_interfaces:
                    try:
                        if not dev.is_opened():
                            dev.open()
                        dev.set_raw_data_handler(self._input_handler)
                    except:
                        pass
                telemetry_data["connected"] = True
                return True
            else:
                telemetry_data["connected"] = False
                return False
        except Exception:
            telemetry_data["connected"] = False
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

        if force or mode != self.last_mode or rpm != self.last_rpm:
            rpm_low = rpm & 0xFF
            rpm_high = (rpm >> 8) & 0xFF
            payload = [0x00, 0x5A, 0xA5, 0x26, 0x05, mode, rpm_low, rpm_high]
            if self.send_packet(payload):
                self.last_mode = mode
                self.last_rpm = rpm
            else:
                self.all_interfaces = [] 
                telemetry_data["connected"] = False

    def probe_status(self):
        if not self.all_interfaces: return
        payload = [0x00, 0x5A, 0xA5, 0x24, 0x05, 0x00, 0x00, 0x00]
        if not self.send_packet(payload):
            self.all_interfaces = []
            telemetry_data["connected"] = False

def get_smart_strategy(temp):
    if temp < 52: return (0, 1000, "微风 (1000)")
    elif temp < 60: return (0, 1300, "静音 (1300)")
    elif temp < 67: return (0, 1700, "柔风 (1700)")
    elif temp < 74: return (1, 2100, "均衡 (2100)")
    elif temp < 82: return (1, 2600, "强效 (2600)")
    elif temp < 88: return (1, 3200, "疾风 (3200)")
    else: return (1, 4000, "⚡狂暴 (4000)")

def main():
    try:
        instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        instance_socket.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))
        instance_socket.listen(0)
    except socket.error:
        sys.exit(0)

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    fan = FlydigiController()
    read_mechrevo_status()
    apply_active_fan_curves(force_boost=False)
    
    poll_counter = 0
    last_ec_heal_time = 0
    last_periodic_ec_sync = time.time()
    while True:
        try:
            if not fan.all_interfaces:
                fan.connect()

            cpu_t, gpu_t = get_hardware_temp()
            telemetry_data["cpu_temp"] = cpu_t
            telemetry_data["gpu_temp"] = gpu_t
            effective_temp = max(cpu_t, gpu_t)
            telemetry_data["max_temp"] = effective_temp

            now = time.time()
            # 异常暴走逃逸自愈检测 (EC Watchdog):
            # 若 CPU 核心温度低于 68℃，但 EC CPU 风扇 duty 却跑满 (>= 80% 或转速 >= 3800 RPM):
            # 表明系统刚刚从锁屏/休眠唤醒，或底层服务/ACPI重置了 EC，立即毫秒级自愈！
            if not telemetry_data.get("internal_fan_boost", False):
                cpu_duty = telemetry_data.get("cpu_fan_duty", 0)
                cpu_rpm = telemetry_data.get("cpu_fan_rpm", 0)
                gpu_duty = telemetry_data.get("gpu_fan_duty", 0)
                gpu_rpm = telemetry_data.get("gpu_fan_rpm", 0)
                
                ec_anomaly = (cpu_t < 68.0 and (cpu_duty >= 80 or cpu_rpm >= 3800)) or \
                             (gpu_t < 65.0 and (gpu_duty >= 80 or gpu_rpm >= 3800))
                
                if ec_anomaly and (now - last_ec_heal_time > 3.0):
                    last_ec_heal_time = now
                    apply_active_fan_curves(force_boost=False)

            if poll_counter % 5 == 0:
                read_mechrevo_status()
            poll_counter += 1

            if telemetry_data["manual_override"]:
                mode = telemetry_data["manual_mode"]
                target_rpm = telemetry_data["manual_rpm"]
            else:
                mode, target_rpm, mode_name = get_smart_strategy(effective_temp)
                telemetry_data["mode_name"] = mode_name

            telemetry_data["mode"] = mode
            telemetry_data["target_rpm"] = target_rpm

            fan.set_fan(mode, target_rpm, force=fan.first_run)
            fan.probe_status()
            
            if fan.first_run: fan.first_run = False
            time.sleep(CHECK_INTERVAL)
            
        except Exception:
            time.sleep(5)
            fan.all_interfaces = []

if __name__ == "__main__":
    main()

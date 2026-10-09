import asyncio
from bleak import BleakClient, BleakScanner

class FlydigiCoolerBLE:
    def __init__(self, mac_address=None, write_uuid=None):
        self.mac = mac_address
        self.uuid = write_uuid # 必填：从手机 nRF Connect 获取
        self.header = [0x5A, 0xA5]

    def _build_packet(self, mode, rpm):
        """构建协议包"""
        # 1. 拆分 RPM (小端序)
        rpm_low = rpm & 0xFF
        rpm_high = (rpm >> 8) & 0xFF
        
        # 2. 组装参数部分 [功能, 固定, 模式, 低位, 高位]
        params = [0x26, 0x05, mode, rpm_low, rpm_high]
        
        # 3. 计算校验和
        checksum = sum(params) & 0xFF
        
        # 4. 返回完整 bytes
        return bytes(self.header + params + [checksum])

    async def set_speed(self, mode, rpm):
        print(f"搜索设备...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and "BS2" in d.name # 根据名字模糊搜索
        )
        if not device:
            print("未找到设备")
            return

        async with BleakClient(device) as client:
            packet = self._build_packet(mode, rpm)
            print(f"发送指令: {packet.hex()}")
            await client.write_gatt_char(self.uuid, packet)
            print("设置成功！")

# 使用示例
# controller = FlydigiCoolerBLE(write_uuid="您的UUID")
# asyncio.run(controller.set_speed(mode=1, rpm=2700))